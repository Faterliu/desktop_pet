from __future__ import annotations

import sys
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from app.chat_flow_controller import ChatFlowController  # noqa: E402


class FakeStore:
    def __init__(self) -> None:
        """初始化当前对象及其依赖。"""
        self.messages: list[tuple[str, str]] = []

    def append_message(self, role: str, content: str) -> None:
        """添加 `append_message` 对应的内容。"""
        self.messages.append((role, content))


class ChatFlowControllerTests(unittest.TestCase):
    def make_controller(
        self,
        *,
        formal: bool = False,
        api_enabled: bool = True,
        api_configured: bool = True,
    ) -> tuple[ChatFlowController, FakeStore, FakeStore]:
        """构建 `make_controller` 所需的结果。"""
        formal_store = FakeStore()
        informal_store = FakeStore()
        controller = ChatFlowController(
            formal_store,
            informal_store,
            formal_qa_enabled=lambda: formal,
            api_chat_enabled=lambda: api_enabled,
            api_configured=lambda: api_configured,
            local_reply_provider=lambda message, formal_mode: (
                f"formal:{message}" if formal_mode else f"local:{message}"
            ),
        )
        return controller, formal_store, informal_store

    def test_local_reply_uses_current_mode_store(self) -> None:
        """验证 `test_local_reply_uses_current_mode_store` 对应的行为。"""
        controller, formal_store, informal_store = self.make_controller(api_enabled=False)

        context = controller.begin_user_message("你好")
        decision = controller.decide_after_thinking(context)

        self.assertEqual(decision.kind, "local_reply")
        self.assertEqual(decision.reply, "local:你好")
        self.assertEqual(informal_store.messages, [("user", "你好"), ("assistant", "local:你好")])
        self.assertEqual(formal_store.messages, [])

    def test_missing_api_config_keeps_existing_reply_text(self) -> None:
        """验证 `test_missing_api_config_keeps_existing_reply_text` 对应的行为。"""
        controller, _formal_store, informal_store = self.make_controller(api_configured=False)

        context = controller.begin_user_message("测试")
        decision = controller.decide_after_thinking(context)

        self.assertEqual(decision.kind, "missing_api_config")
        self.assertIn("DeepSeek API key", decision.reply)
        self.assertEqual(informal_store.messages[-1], ("assistant", decision.reply))

    def test_formal_success_appends_to_formal_store_and_returns_question(self) -> None:
        """验证 `test_formal_success_appends_to_formal_store_and_returns_question` 对应的行为。"""
        controller, formal_store, informal_store = self.make_controller(formal=True)

        controller.begin_user_message("如何实现？")
        completion = controller.complete_success("  答案  ")

        self.assertEqual(completion.reply, "答案")
        self.assertEqual(completion.question, "如何实现？")
        self.assertTrue(completion.formal_qa_mode)
        self.assertEqual(formal_store.messages, [("user", "如何实现？"), ("assistant", "答案")])
        self.assertEqual(informal_store.messages, [])
        self.assertFalse(controller.pending_was_formal)
        self.assertEqual(controller.pending_question, "")

    def test_worker_kwargs_use_pending_formal_snapshot(self) -> None:
        """验证 `test_worker_kwargs_use_pending_formal_snapshot` 对应的行为。"""
        controller, _formal_store, _informal_store = self.make_controller(formal=True)
        controller.begin_user_message("正式问题")

        kwargs = controller.chat_worker_kwargs(
            "正式问题",
            client="client",
            prompt_builder="prompt",
            context_manager="context",
            mem0_memory_service="mem0",
            user_id="user",
            app_config={"api": {}},
        )

        self.assertTrue(kwargs["formal_qa_mode"])
        self.assertEqual(kwargs["user_message"], "正式问题")
        self.assertEqual(kwargs["user_id"], "user")

    def test_can_start_chat_rejects_registered_chat_task(self) -> None:
        """验证 `test_can_start_chat_rejects_registered_chat_task` 对应的行为。"""
        controller, _formal_store, _informal_store = self.make_controller()

        self.assertFalse(controller.can_start_chat(True))
        self.assertTrue(controller.can_start_chat(False))


if __name__ == "__main__":
    unittest.main()
