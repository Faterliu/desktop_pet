from __future__ import annotations

import logging
import shutil
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

logger_module = types.ModuleType("utils.logger")
logger_module.get_logger = logging.getLogger
sys.modules.setdefault("utils.logger", logger_module)

from ai.llm_client import ReminderToolCall, ToolChatResponse  # noqa: E402
from app.desktop_pet_window import ChatWorker, ChatWorkerResult  # noqa: E402
from app.reminder_tool import ReminderTool  # noqa: E402
from storage.reminder_store import ReminderStore  # noqa: E402


class FakeContextManager:
    # 返回空历史，避免测试依赖聊天存储。
    def recent_messages(self, formal_qa_mode: bool) -> list[dict]:
        """返回空历史，避免测试依赖聊天存储。"""
        _ = formal_qa_mode
        return []


class FakePromptBuilder:
    # 记录提醒提示，并返回可供客户端检查的最小消息列表。
    def __init__(self) -> None:
        """记录提醒提示，并返回可供客户端检查的最小消息列表。"""
        self.reminder_guidance = None

    # 构建最小消息列表。
    def build_messages(self, user_message: str, recent_messages: list[dict], **kwargs) -> list[dict]:
        """构建最小消息列表。"""
        _ = recent_messages
        self.reminder_guidance = kwargs.get("reminder_tool_guidance")
        return [{"role": "user", "content": user_message}]


class FakeClient:
    # 初始化固定的模型工具响应。
    def __init__(self, response: ToolChatResponse) -> None:
        """初始化固定的模型工具响应。"""
        self.response = response
        self.tool_calls = 0
        self.plain_calls = 0

    # 返回固定工具响应。
    def chat_with_reminder_tools(self, messages, fallback_messages):  # type: ignore[no-untyped-def]
        """返回固定工具响应。"""
        _ = messages, fallback_messages
        self.tool_calls += 1
        return self.response

    # 返回固定普通回复。
    def chat(self, messages):  # type: ignore[no-untyped-def]
        """返回固定普通回复。"""
        _ = messages
        self.plain_calls += 1
        return "普通回复"


class ChatWorkerReminderTests(unittest.TestCase):
    # 为测试准备可写路径和固定当前时间。
    def setUp(self) -> None:
        """为测试准备可写路径和固定当前时间。"""
        self.temp_dir = DESKTOP_PET_ROOT / "tmp_work" / "test_chat_worker_reminders" / self._testMethodName
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.now = datetime(2026, 7, 10, 12, 0)
        self.store = ReminderStore(self.temp_dir / "reminders.json")
        self.tool = ReminderTool(
            self.store,
            enabled_provider=lambda: True,
            max_active_provider=lambda: 20,
            now_provider=lambda: self.now,
        )

    # 清理测试目录。
    def tearDown(self) -> None:
        """清理测试目录。"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    # 验证工作线程会执行最多三条模型提醒调用并发出确认文本。
    def test_worker_creates_multiple_model_reminders(self) -> None:
        """验证工作线程会执行最多三条模型提醒调用并发出确认文本。"""
        client = FakeClient(
            ToolChatResponse(
                "",
                [
                    ReminderToolCall("开会", "2026-07-10T13:00:00"),
                    ReminderToolCall("取快递", "2026-07-10T14:00:00"),
                ],
                "native",
            )
        )
        prompt_builder = FakePromptBuilder()
        worker = ChatWorker(
            "下午提醒我开会和取快递",
            client,  # type: ignore[arg-type]
            prompt_builder,  # type: ignore[arg-type]
            FakeContextManager(),  # type: ignore[arg-type]
            formal_qa_mode=False,
            reminder_tool=self.tool,
        )
        replies: list[ChatWorkerResult] = []
        worker.finished.connect(replies.append)

        worker.run()

        self.assertEqual(client.tool_calls, 1)
        self.assertIn("本地提醒工具", prompt_builder.reminder_guidance)
        self.assertEqual(len(self.store.list_reminders("active")), 2)
        self.assertIn("2 条提醒", replies[0].reply)
        self.assertTrue(replies[0].created_reminders)

    # 验证未返回提醒调用时不会写入提醒存储。
    def test_worker_does_not_create_reminder_for_plain_reply(self) -> None:
        """验证未返回提醒调用时不会写入提醒存储。"""
        client = FakeClient(ToolChatResponse("普通回答", [], "native"))
        worker = ChatWorker(
            "今天天气怎么样",
            client,  # type: ignore[arg-type]
            FakePromptBuilder(),  # type: ignore[arg-type]
            FakeContextManager(),  # type: ignore[arg-type]
            formal_qa_mode=False,
            reminder_tool=self.tool,
        )
        replies: list[ChatWorkerResult] = []
        worker.finished.connect(replies.append)

        worker.run()

        self.assertEqual(self.store.list_reminders("active"), [])
        self.assertEqual(replies, [ChatWorkerResult("普通回答")])

    # 验证工具校验失败时不会展示模型的错误成功确认。
    def test_worker_uses_local_failure_reply_when_tool_rejects_call(self) -> None:
        """验证工具校验失败时不会展示模型的错误成功确认。"""
        client = FakeClient(
            ToolChatResponse(
                "已经帮你设置好了",
                [ReminderToolCall("过期提醒", "2026-07-10T11:00:00")],
                "native",
            )
        )
        worker = ChatWorker(
            "提醒我刚才开会",
            client,  # type: ignore[arg-type]
            FakePromptBuilder(),  # type: ignore[arg-type]
            FakeContextManager(),  # type: ignore[arg-type]
            formal_qa_mode=False,
            reminder_tool=self.tool,
        )
        replies: list[ChatWorkerResult] = []
        worker.finished.connect(replies.append)

        worker.run()

        self.assertEqual(self.store.list_reminders("active"), [])
        self.assertIn("已经过去", replies[0].reply)
        self.assertFalse(replies[0].created_reminders)


if __name__ == "__main__":
    unittest.main()
