from __future__ import annotations

import sys
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from app.chat_flow_controller import ChatFlowController  # noqa: E402
from character.emotion_state import EmotionState  # noqa: E402
from character.persona_state import PersonaState  # noqa: E402


class FakeStore:
    # 初始化当前对象及其依赖。
    def __init__(self) -> None:
        """初始化当前对象及其依赖。"""
        self.messages: list[tuple[str, str, dict | None]] = []
        self.reassigned: list[tuple[str, str]] = []

    # 为 FakeStore 测试替身提供append 消息行为。
    def append_message(self, role: str, content: str, metadata: dict | None = None) -> None:
        """为 FakeStore 测试替身提供append 消息行为。"""
        self.messages.append((role, content, metadata))

    # 记录会话重标调用，模拟 JSONL 模式切换。
    def reassign_conversation(self, conversation_id: str, target_mode: str) -> None:
        """记录会话重标调用。"""
        self.reassigned.append((conversation_id, target_mode))


class ChatFlowControllerTests(unittest.TestCase):
    # 为测试准备make 控制器数据或断言辅助结果。
    def make_controller(
        self,
        *,
        formal: bool = False,
        api_enabled: bool = True,
        api_configured: bool = True,
    ) -> tuple[ChatFlowController, FakeStore, FakeStore]:
        """为测试准备make 控制器数据或断言辅助结果。"""
        formal_store = FakeStore()
        informal_store = FakeStore()
        controller = ChatFlowController(
            formal_store,
            informal_store,
            formal_qa_enabled=lambda: formal,
            api_chat_enabled=lambda: api_enabled,
            api_configured=lambda: api_configured,
            local_reply_provider=lambda message, formal_mode, _state: (
                f"formal:{message}" if formal_mode else f"local:{message}"
            ),
        )
        return controller, formal_store, informal_store

    # 验证本地 回复 uses current 模式 存储场景下的预期结果。
    def test_local_reply_uses_current_mode_store(self) -> None:
        """验证本地 回复 uses current 模式 存储场景下的预期结果。"""
        controller, formal_store, informal_store = self.make_controller(api_enabled=False)

        context = controller.begin_user_message("你好")
        decision = controller.decide_after_thinking(context)

        self.assertEqual(decision.kind, "local_reply")
        self.assertEqual(decision.reply, "local:你好")
        self.assertEqual(
            [(role, content) for role, content, _metadata in informal_store.messages],
            [("user", "你好"), ("assistant", "local:你好")],
        )
        self.assertEqual(formal_store.messages, [])

    # 验证missing API 配置 keeps existing 回复 文本场景下的预期结果。
    def test_missing_api_config_keeps_existing_reply_text(self) -> None:
        """验证missing API 配置 keeps existing 回复 文本场景下的预期结果。"""
        controller, _formal_store, informal_store = self.make_controller(api_configured=False)

        context = controller.begin_user_message("测试")
        decision = controller.decide_after_thinking(context)

        self.assertEqual(decision.kind, "missing_api_config")
        self.assertIn("当前模型提供商的 API key", decision.reply)
        self.assertEqual(informal_store.messages[-1][:2], ("assistant", decision.reply))

    # 验证正式问答 success appends to 正式问答 存储 and returns question场景下的预期结果。
    def test_formal_success_appends_to_formal_store_and_returns_question(self) -> None:
        """验证正式问答 success appends to 正式问答 存储 and returns question场景下的预期结果。"""
        controller, formal_store, informal_store = self.make_controller(formal=True)

        controller.begin_user_message("如何实现？")
        completion = controller.complete_success("  答案  ")

        self.assertEqual(completion.reply, "答案")
        self.assertEqual(completion.question, "如何实现？")
        self.assertTrue(completion.formal_qa_mode)
        self.assertEqual(
            [(role, content) for role, content, _metadata in formal_store.messages],
            [("user", "如何实现？"), ("assistant", "答案")],
        )
        self.assertEqual(informal_store.messages, [])
        self.assertFalse(controller.pending_was_formal)
        self.assertEqual(controller.pending_question, "")

    # 验证成功提醒会按当前会话标识把两条记录改标为 remind。
    def test_successful_reminder_reassigns_current_conversation(self) -> None:
        """验证成功提醒会按当前会话标识把两条记录改标为 remind。"""
        controller, _formal_store, informal_store = self.make_controller()

        controller.begin_user_message("十分钟后提醒我休息")
        controller.complete_success("好的，十分钟后提醒你。", move_to_remind=True)

        self.assertEqual(len(informal_store.reassigned), 1)
        self.assertEqual(informal_store.reassigned[0][1], "remind")
        conversation_ids = {
            metadata["conversation_id"]
            for _role, _content, metadata in informal_store.messages
            if metadata is not None
        }
        self.assertEqual({informal_store.reassigned[0][0]}, conversation_ids)

    # 验证工作线程 kwargs use pending 正式问答 snapshot场景下的预期结果。
    def test_worker_kwargs_use_pending_formal_snapshot(self) -> None:
        """验证工作线程 kwargs use pending 正式问答 snapshot场景下的预期结果。"""
        controller, _formal_store, _informal_store = self.make_controller(formal=True)
        persona_state = PersonaState(EmotionState.THINKING, "high", 0.56, "formal")
        context = controller.begin_user_message("正式问题", persona_state)

        kwargs = controller.chat_worker_kwargs(
            "正式问题",
            client="client",
            prompt_builder="prompt",
            context_manager="context",
        )

        self.assertTrue(kwargs["formal_qa_mode"])
        self.assertEqual(kwargs["user_message"], "正式问题")
        self.assertIs(context.runtime_persona_state, persona_state)
        self.assertIs(kwargs["runtime_persona_state"], persona_state)

    # 验证本地回复提供器接收当前消息对应的状态快照。
    def test_local_reply_provider_receives_persona_state_snapshot(self) -> None:
        """本地分支必须使用与 API 分支相同的动态状态快照。"""
        received: list[PersonaState] = []
        formal_store = FakeStore()
        informal_store = FakeStore()
        controller = ChatFlowController(
            formal_store,
            informal_store,
            formal_qa_enabled=lambda: False,
            api_chat_enabled=lambda: False,
            api_configured=lambda: True,
            local_reply_provider=lambda _message, _formal, state: received.append(state) or "回复",
        )
        persona_state = PersonaState(EmotionState.SAD, "low", 0.48, "emotional_support")

        context = controller.begin_user_message("我很焦虑", persona_state)
        controller.decide_after_thinking(context)

        self.assertEqual(received, [persona_state])

    # 验证can start 聊天 rejects registered 聊天 任务场景下的预期结果。
    def test_can_start_chat_rejects_registered_chat_task(self) -> None:
        """验证can start 聊天 rejects registered 聊天 任务场景下的预期结果。"""
        controller, _formal_store, _informal_store = self.make_controller()

        self.assertFalse(controller.can_start_chat(True))
        self.assertTrue(controller.can_start_chat(False))


if __name__ == "__main__":
    unittest.main()
