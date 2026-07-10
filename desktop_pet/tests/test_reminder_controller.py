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

    # 验证启动时会补发已过期的 active 提醒并标记完成。
    def test_start_claims_overdue_active_reminder_once(self) -> None:
        """验证启动时会补发已过期的 active 提醒并标记完成。"""
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
            self.assertEqual(store.get_reminder(reminder["id"])["status"], "done")  # type: ignore[index]

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
            self.assertEqual(store.get_reminder(reminder["id"])["status"], "done")  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
