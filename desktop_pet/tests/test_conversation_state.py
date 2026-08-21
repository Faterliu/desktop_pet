from __future__ import annotations

import sys
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from character.conversation_state import ConversationStateController  # noqa: E402
from character.emotion_state import EmotionState  # noqa: E402


class ConversationStateControllerTests(unittest.TestCase):
    """验证本地动态对话状态与精灵动作映射。"""

    def setUp(self) -> None:
        """为每个测试创建独立的会话状态。"""
        self.controller = ConversationStateController()

    def test_message_categories_produce_expected_states_and_actions(self) -> None:
        """典型用户表达应得到保守且稳定的状态分类。"""
        cases = [
            ("你好", False, EmotionState.HAPPY, "normal", "companion", "waving"),
            ("这个 bug 为什么报错", False, EmotionState.THINKING, "normal", "task", "review"),
            ("我好累", False, EmotionState.SLEEPY, "low", "emotional_support", "waiting"),
            ("终于成功了", False, EmotionState.HAPPY, "high", "companion", "jumping"),
            ("今天随便聊聊", False, EmotionState.CALM, "normal", "companion", "running"),
        ]

        for message, formal, mood, energy, mode, action in cases:
            with self.subTest(message=message):
                self.controller.reset()
                state = self.controller.update(message, formal)
                plan = self.controller.action_plan(state, waiting_for_api=True)
                self.assertEqual(state.mood, mood)
                self.assertEqual(state.energy, energy)
                self.assertEqual(state.mode, mode)
                self.assertEqual(plan.action_name, action)

    def test_formal_mode_overrides_emotion_and_task_signals(self) -> None:
        """正式模式始终使用正式思考状态。"""
        state = self.controller.update("我好累，这个 bug 又报错了", True)

        self.assertEqual(state.mood, EmotionState.THINKING)
        self.assertEqual(state.energy, "normal")
        self.assertEqual(state.mode, "formal")
        self.assertEqual(
            self.controller.action_plan(state, waiting_for_api=True).action_name,
            "review",
        )

    def test_explicit_emotion_precedes_task_signal_in_informal_mode(self) -> None:
        """闲聊中明确情绪优先，后续提示词仍可根据原消息完成任务。"""
        state = self.controller.update("我很焦虑，帮我修复这个 bug", False)

        self.assertEqual(state.mood, EmotionState.SAD)
        self.assertEqual(state.mode, "emotional_support")

    def test_closeness_changes_once_per_message_and_is_clamped(self) -> None:
        """一条消息即使含有多个友好词也只能调整一次亲近度。"""
        state = self.controller.update("你好，谢谢你，终于成功了", False)
        self.assertEqual(state.closeness, 0.52)

        for _ in range(20):
            state = self.controller.update("谢谢", False)
        self.assertEqual(state.closeness, 0.65)

        for _ in range(20):
            state = self.controller.update("别烦我，也不要打扰我", False)
        self.assertEqual(state.closeness, 0.35)

    def test_proactive_response_can_raise_closeness_without_friendly_words(self) -> None:
        """明确回应主动问候时允许小幅增加当前会话亲近度。"""
        state = self.controller.update("嗯", False, proactive_response=True)

        self.assertEqual(state.closeness, 0.52)

    def test_negated_emotion_is_not_treated_as_explicit_distress(self) -> None:
        """常见否定表达不能被误判为负面情绪。"""
        state = self.controller.update("我不焦虑，也不累", False)

        self.assertEqual(state.mood, EmotionState.CALM)
        self.assertEqual(state.mode, "companion")

    def test_local_action_plays_one_cycle_and_returns_idle(self) -> None:
        """本地即时回复使用单轮动作，避免被立即重置。"""
        state = self.controller.update("这个 bug 报错了", False)
        plan = self.controller.action_plan(state, waiting_for_api=False)

        self.assertEqual(plan.action_name, "review")
        self.assertEqual(plan.fallback_action, "idle")
        self.assertTrue(plan.force_single_cycle)

    def test_api_greeting_action_falls_back_to_waiting(self) -> None:
        """问候动作播放完后应继续等待 API，而不是提前回到空闲。"""
        state = self.controller.update("你好", False)
        plan = self.controller.action_plan(state, waiting_for_api=True)

        self.assertEqual(plan.action_name, "waving")
        self.assertEqual(plan.fallback_action, "waiting")
        self.assertTrue(plan.force_single_cycle)


if __name__ == "__main__":
    unittest.main()
