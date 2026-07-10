from __future__ import annotations

import logging
import shutil
import sys
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

logger_module = types.ModuleType("utils.logger")
logger_module.get_logger = logging.getLogger
sys.modules.setdefault("utils.logger", logger_module)

from app.reminder_tool import ReminderTool, ReminderToolRequest  # noqa: E402
from storage.reminder_store import ReminderStore  # noqa: E402


class ReminderToolTests(unittest.TestCase):
    # 为每个测试准备独立的工作区临时目录。
    def setUp(self) -> None:
        """为每个测试准备独立的工作区临时目录。"""
        self.temp_dir = DESKTOP_PET_ROOT / "tmp_work" / "test_reminder_tool" / self._testMethodName
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.now = datetime(2026, 7, 10, 12, 0)
        self.store = ReminderStore(self.temp_dir / "reminders.json")
        self.enabled = True
        self.max_active = 3
        self.tool = ReminderTool(
            self.store,
            enabled_provider=lambda: self.enabled,
            max_active_provider=lambda: self.max_active,
            now_provider=lambda: self.now,
        )

    # 清理当前测试目录。
    def tearDown(self) -> None:
        """清理当前测试目录。"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    # 验证工具会以模型来源写入一条未来提醒。
    def test_create_reminder_persists_model_source(self) -> None:
        """验证工具会以模型来源写入一条未来提醒。"""
        result = self.tool.create_reminder(
            "修改论文表格",
            "2026-07-10T12:30:00",
            source="model_tool_native",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.code, "created")
        self.assertEqual(result.reminder["source"], "model_tool_native")  # type: ignore[index]

    # 验证空标题、过去时间和上限均不会创建提醒。
    def test_invalid_input_and_limit_do_not_persist(self) -> None:
        """验证空标题、过去时间和上限均不会创建提醒。"""
        self.assertEqual(
            self.tool.create_reminder("", "2026-07-10T12:30:00").code,
            "empty_title",
        )
        self.assertEqual(
            self.tool.create_reminder("已过期", "2026-07-10T11:59:59").code,
            "invalid_or_past_due_at",
        )
        self.max_active = 1
        self.store.add_reminder("已有提醒", self.now + timedelta(minutes=1))
        self.assertEqual(
            self.tool.create_reminder("超出上限", "2026-07-10T12:30:00").code,
            "active_reminder_limit",
        )
        self.assertEqual(len(self.store.list_reminders("active")), 1)

    # 验证批量调用最多三条，并在预检失败时不产生部分写入。
    def test_create_reminders_limits_count_and_prevalidates_batch(self) -> None:
        """验证批量调用最多三条，并在预检失败时不产生部分写入。"""
        requests = [
            ReminderToolRequest("提醒一", "2026-07-10T12:10:00"),
            ReminderToolRequest("提醒二", "2026-07-10T12:20:00"),
            ReminderToolRequest("提醒三", "2026-07-10T12:30:00"),
        ]
        results = self.tool.create_reminders(requests, source="model_tool_json")
        self.assertTrue(all(item.success for item in results))
        self.assertEqual(len(self.store.list_reminders("active")), 3)

        failed = self.tool.create_reminders(
            [ReminderToolRequest("无效", "not-a-date")],
            source="model_tool_json",
        )
        self.assertEqual(failed[0].code, "invalid_or_past_due_at")
        self.assertEqual(len(self.store.list_reminders("active")), 3)


if __name__ == "__main__":
    unittest.main()
