from __future__ import annotations

import logging
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

    # 验证领取到期提醒会标记完成，且之后不会再次被领取。
    def test_claim_due_reminders_marks_done_once(self) -> None:
        """验证领取到期提醒会标记完成，且之后不会再次被领取。"""
        with tempfile.TemporaryDirectory() as temp:
            store = ReminderStore(Path(temp) / "reminders.json")
            now = datetime(2026, 7, 10, 12, 0)
            due = store.add_reminder("休息一下", now - timedelta(seconds=1))
            active = store.add_reminder("下午开会", now + timedelta(minutes=10))

            claimed = store.claim_due_reminders(now)

            self.assertEqual([item["id"] for item in claimed], [due["id"]])
            self.assertEqual(store.get_reminder(due["id"])["status"], "done")  # type: ignore[index]
            self.assertEqual(store.get_reminder(active["id"])["status"], "active")  # type: ignore[index]
            self.assertEqual(store.claim_due_reminders(now), [])

    # 验证清空已完成提醒不会改变 active 提醒。
    def test_clear_completed_reminders_keeps_active_reminders(self) -> None:
        """验证清空已完成提醒不会改变 active 提醒。"""
        with tempfile.TemporaryDirectory() as temp:
            store = ReminderStore(Path(temp) / "reminders.json")
            now = datetime(2026, 7, 10, 12, 0)
            done = store.add_reminder("已完成事项", now - timedelta(minutes=1))
            active = store.add_reminder("待办事项", now + timedelta(minutes=1))
            store.claim_due_reminders(now)

            self.assertEqual(store.clear_completed_reminders(), 1)
            self.assertIsNone(store.get_reminder(done["id"]))
            self.assertEqual(store.get_reminder(active["id"])["status"], "active")  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
