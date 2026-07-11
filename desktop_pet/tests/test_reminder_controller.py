from __future__ import annotations

import logging
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

logger_module = types.ModuleType("utils.logger")
logger_module.get_logger = logging.getLogger
sys.modules.setdefault("utils.logger", logger_module)

from PySide6.QtCore import QCoreApplication  # noqa: E402

from app.reminder_controller import ReminderController  # noqa: E402
from storage.reminder_store import ReminderStore  # noqa: E402


class ReminderControllerTests(unittest.TestCase):
    # 准备 Qt 定时器所需的应用实例。
    @classmethod
    def setUpClass(cls) -> None:
        """准备 Qt 定时器所需的应用实例。"""
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    # 验证启动时会补发已过期的 active 提醒并等待用户确认。
    def test_start_claims_overdue_active_reminder_once(self) -> None:
        """验证启动时会补发已过期的 active 提醒并等待用户确认。"""
        with tempfile.TemporaryDirectory() as temp:
            store = ReminderStore(Path(temp) / "reminders.json")
            now = datetime(2026, 7, 10, 12, 0)
            reminder = store.add_reminder("修改论文表格", now - timedelta(minutes=1))
            delivered: list[dict] = []
            controller = ReminderController(
                store,
                check_interval_seconds=30,
                now_provider=lambda: now,
            )
            controller.reminder_due.connect(delivered.append)

            controller.start()
            controller.check_due_reminders()
            controller.stop()

            self.assertEqual([item["id"] for item in delivered], [reminder["id"]])
            self.assertEqual(store.get_reminder(reminder["id"])["status"], "awaiting_ack")  # type: ignore[index]

    # 验证被免打扰策略暂缓的到期提醒会保持 active，恢复后再补发。
    def test_deferred_delivery_keeps_reminder_active_until_allowed(self) -> None:
        """验证被免打扰策略暂缓的到期提醒会保持 active，恢复后再补发。"""
        with tempfile.TemporaryDirectory() as temp:
            store = ReminderStore(Path(temp) / "reminders.json")
            now = datetime(2026, 7, 10, 12, 0)
            reminder = store.add_reminder("休息一下", now - timedelta(minutes=1))
            allowed = False
            delivered: list[dict] = []
            controller = ReminderController(
                store,
                can_deliver=lambda: allowed,
                now_provider=lambda: now,
            )
            controller.reminder_due.connect(delivered.append)

            self.assertEqual(controller.check_due_reminders(), [])
            self.assertEqual(store.get_reminder(reminder["id"])["status"], "active")  # type: ignore[index]
            allowed = True
            controller.check_due_reminders()

            self.assertEqual([item["id"] for item in delivered], [reminder["id"]])
            self.assertEqual(store.get_reminder(reminder["id"])["status"], "awaiting_ack")  # type: ignore[index]

    # 验证待确认提醒到达设定间隔后会再次投递。
    def test_waiting_reminder_is_redelivered_after_ack_repeat_interval(self) -> None:
        """验证待确认提醒到达设定间隔后会再次投递。"""
        with tempfile.TemporaryDirectory() as temp:
            store = ReminderStore(Path(temp) / "reminders.json")
            now = datetime(2026, 7, 10, 12, 0)
            reminder = store.add_reminder("确认提醒", now - timedelta(minutes=1))
            clock = {"now": now}
            delivered: list[dict] = []
            controller = ReminderController(
                store,
                now_provider=lambda: clock["now"],
                ack_repeat_minutes=5,
            )
            controller.reminder_due.connect(delivered.append)

            controller.check_due_reminders()
            clock["now"] = now + timedelta(minutes=4)
            controller.check_due_reminders()
            clock["now"] = now + timedelta(minutes=5)
            controller.check_due_reminders()

            self.assertEqual([item["id"] for item in delivered], [reminder["id"], reminder["id"]])

    # 验证启动补查即使暂时无法投递，也会清理过期的已完成提醒。
    def test_start_cleans_expired_done_reminders_when_delivery_is_deferred(self) -> None:
        """验证启动补查即使暂时无法投递，也会清理过期的已完成提醒。"""
        with tempfile.TemporaryDirectory() as temp:
            store = ReminderStore(Path(temp) / "reminders.json")
            now = datetime(2026, 7, 10, 12, 0)
            expired_done = store.add_reminder("旧提醒", now - timedelta(days=8, minutes=1))
            pending_active = store.add_reminder("待投递提醒", now - timedelta(minutes=1))
            store.claim_due_reminders(now - timedelta(days=8))
            store.acknowledge_reminder(expired_done["id"], now - timedelta(days=8))
            controller = ReminderController(
                store,
                can_deliver=lambda: False,
                now_provider=lambda: now,
                completed_retention_days=7,
            )

            controller.start()
            controller.stop()

            self.assertIsNone(store.get_reminder(expired_done["id"]))
            self.assertEqual(store.get_reminder(pending_active["id"])["status"], "active")  # type: ignore[index]

    # 验证每次定时检查均会按最新时间清理超过保留期的完成提醒。
    def test_check_due_reminders_cleans_completed_reminders_on_later_cycle(self) -> None:
        """验证每次定时检查均会按最新时间清理超过保留期的完成提醒。"""
        with tempfile.TemporaryDirectory() as temp:
            store = ReminderStore(Path(temp) / "reminders.json")
            now = datetime(2026, 7, 10, 12, 0)
            reminder = store.add_reminder("完成提醒", now - timedelta(minutes=1))
            store.claim_due_reminders(now)
            store.acknowledge_reminder(reminder["id"], now)
            clock = {"now": now}
            controller = ReminderController(
                store,
                now_provider=lambda: clock["now"],
                completed_retention_days=7,
            )

            controller.check_due_reminders()
            self.assertIsNotNone(store.get_reminder(reminder["id"]))
            clock["now"] = now + timedelta(days=7)
            controller.check_due_reminders()

            self.assertIsNone(store.get_reminder(reminder["id"]))


if __name__ == "__main__":
    unittest.main()
