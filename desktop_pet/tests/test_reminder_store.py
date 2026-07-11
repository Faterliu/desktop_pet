from __future__ import annotations

import logging
import json
import tempfile
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(DESKTOP_PET_ROOT))

logger_module = types.ModuleType("utils.logger")
logger_module.get_logger = logging.getLogger
sys.modules.setdefault("utils.logger", logger_module)

from storage.reminder_store import ReminderStore  # noqa: E402


class ReminderStoreTests(unittest.TestCase):
    # 验证提醒的创建、查询、更新和删除保持字段完整。
    def test_create_read_update_and_delete_reminder(self) -> None:
        """验证提醒的创建、查询、更新和删除保持字段完整。"""
        with tempfile.TemporaryDirectory() as temp:
            store = ReminderStore(Path(temp) / "reminders.json")
            reminder = store.add_reminder(
                "修改论文表格",
                datetime(2026, 7, 10, 12, 30),
                source="chat_command",
            )

            self.assertEqual(reminder["status"], "active")
            self.assertEqual(reminder["title"], "修改论文表格")
            self.assertTrue(reminder["id"])
            self.assertEqual(store.get_reminder(reminder["id"]), reminder)

            updated = store.update_reminder(reminder["id"], title="完成论文表格")
            self.assertIsNotNone(updated)
            self.assertEqual(updated["title"], "完成论文表格")  # type: ignore[index]
            self.assertTrue(store.delete_reminder(reminder["id"]))
            self.assertIsNone(store.get_reminder(reminder["id"]))

    # 验证到期提醒进入待确认状态，并按间隔允许再次领取。
    def test_claim_due_reminders_waits_for_ack_and_repeats(self) -> None:
        """验证到期提醒进入待确认状态，并按间隔允许再次领取。"""
        with tempfile.TemporaryDirectory() as temp:
            store = ReminderStore(Path(temp) / "reminders.json")
            now = datetime(2026, 7, 10, 12, 0)
            due = store.add_reminder("休息一下", now - timedelta(seconds=1))
            active = store.add_reminder("下午开会", now + timedelta(minutes=10))

            claimed = store.claim_due_reminders(now)

            self.assertEqual([item["id"] for item in claimed], [due["id"]])
            self.assertEqual(store.get_reminder(due["id"])["status"], "awaiting_ack")  # type: ignore[index]
            self.assertEqual(store.get_reminder(due["id"])["notified_at"], now.isoformat(timespec="seconds"))  # type: ignore[index]
            self.assertEqual(store.get_reminder(due["id"])["completed_at"], "")  # type: ignore[index]
            self.assertEqual(store.get_reminder(active["id"])["status"], "active")  # type: ignore[index]
            self.assertEqual(store.claim_due_reminders(now), [])
            repeated = store.claim_due_reminders(now + timedelta(minutes=5))
            self.assertEqual([item["id"] for item in repeated], [due["id"]])

            completed = store.acknowledge_reminder(due["id"], now + timedelta(minutes=5))
            self.assertIsNotNone(completed)
            self.assertEqual(completed["status"], "done")  # type: ignore[index]
            self.assertEqual(
                completed["completed_at"],
                (now + timedelta(minutes=5)).isoformat(timespec="seconds"),
            )  # type: ignore[index]

    # 验证待确认提醒延后后恢复 active，并按新的到期时间再次提示。
    def test_snooze_reminder_reschedules_waiting_reminder(self) -> None:
        """验证待确认提醒延后后恢复 active，并按新的到期时间再次提示。"""
        with tempfile.TemporaryDirectory() as temp:
            store = ReminderStore(Path(temp) / "reminders.json")
            now = datetime(2026, 7, 10, 12, 0)
            reminder = store.add_reminder("休息一下", now - timedelta(minutes=1))
            store.claim_due_reminders(now)

            snoozed = store.snooze_reminder(reminder["id"], 10, now)

            self.assertIsNotNone(snoozed)
            self.assertEqual(snoozed["status"], "active")  # type: ignore[index]
            self.assertEqual(snoozed["due_at"], "2026-07-10T12:10:00")  # type: ignore[index]
            self.assertEqual(store.claim_due_reminders(now + timedelta(minutes=9)), [])
            claimed = store.claim_due_reminders(now + timedelta(minutes=10))
            self.assertEqual([item["id"] for item in claimed], [reminder["id"]])
            self.assertEqual(store.get_reminder(reminder["id"])["status"], "awaiting_ack")  # type: ignore[index]

    # 验证清空已完成提醒不会改变 active 提醒。
    def test_clear_completed_reminders_keeps_active_reminders(self) -> None:
        """验证清空已完成提醒不会改变 active 提醒。"""
        with tempfile.TemporaryDirectory() as temp:
            store = ReminderStore(Path(temp) / "reminders.json")
            now = datetime(2026, 7, 10, 12, 0)
            done = store.add_reminder("已完成事项", now - timedelta(minutes=1))
            active = store.add_reminder("待办事项", now + timedelta(minutes=1))
            store.claim_due_reminders(now)
            store.acknowledge_reminder(done["id"], now)

            self.assertEqual(store.clear_completed_reminders(), 1)
            self.assertIsNone(store.get_reminder(done["id"]))
            self.assertEqual(store.get_reminder(active["id"])["status"], "active")  # type: ignore[index]

    # 验证自动清理只删除超过保留期的 done 提醒。
    def test_delete_expired_completed_reminders_keeps_active_and_cancelled(self) -> None:
        """验证自动清理只删除超过保留期的 done 提醒。"""
        with tempfile.TemporaryDirectory() as temp:
            store = ReminderStore(Path(temp) / "reminders.json")
            now = datetime(2026, 7, 10, 12, 0)
            done = store.add_reminder("已完成事项", now - timedelta(minutes=1))
            awaiting_ack = store.add_reminder("待确认事项", now - timedelta(minutes=2))
            active = store.add_reminder("待办事项", now + timedelta(minutes=1))
            cancelled = store.add_reminder("已取消事项", now + timedelta(minutes=2))
            store.claim_due_reminders(now)
            store.acknowledge_reminder(done["id"], now)
            store.cancel_reminder(cancelled["id"])

            self.assertEqual(
                store.delete_expired_completed_reminders(7, now + timedelta(days=6)),
                0,
            )
            self.assertIsNotNone(store.get_reminder(done["id"]))
            self.assertEqual(
                store.delete_expired_completed_reminders(7, now + timedelta(days=7)),
                1,
            )
            self.assertIsNone(store.get_reminder(done["id"]))
            self.assertEqual(store.get_reminder(awaiting_ack["id"])["status"], "awaiting_ack")  # type: ignore[index]
            self.assertEqual(store.get_reminder(active["id"])["status"], "active")  # type: ignore[index]
            self.assertEqual(store.get_reminder(cancelled["id"])["status"], "cancelled")  # type: ignore[index]

    # 验证旧版缺少 completed_at 的 done 提醒会按 due_at 进行清理。
    def test_cleanup_legacy_done_reminder_uses_due_at(self) -> None:
        """验证旧版缺少 completed_at 的 done 提醒会按 due_at 进行清理。"""
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "reminders.json"
            now = datetime(2026, 7, 10, 12, 0)
            legacy_done = {
                "id": "legacy-done",
                "title": "旧完成提醒",
                "due_at": (now - timedelta(days=8)).isoformat(timespec="seconds"),
                "created_at": (now - timedelta(days=9)).isoformat(timespec="seconds"),
                "status": "done",
                "source": "legacy",
            }
            legacy_cancelled = {
                **legacy_done,
                "id": "legacy-cancelled",
                "status": "cancelled",
            }
            path.write_text(
                json.dumps({"reminders": [legacy_done, legacy_cancelled]}),
                encoding="utf-8",
            )
            store = ReminderStore(path)

            self.assertEqual(store.delete_expired_completed_reminders(7, now), 1)
            self.assertIsNone(store.get_reminder("legacy-done"))
            self.assertEqual(store.get_reminder("legacy-cancelled")["status"], "cancelled")  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
