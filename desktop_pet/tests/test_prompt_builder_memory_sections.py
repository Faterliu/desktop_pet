from __future__ import annotations

import sys
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from ai.prompt_builder import PromptBuilder  # noqa: E402
from character.emotion_state import EmotionState, parse_emotion_state  # noqa: E402
from character.persona_state import PersonaState, read_persona_state  # noqa: E402
from storage.json_store import save_json  # noqa: E402


class PromptBuilderMemorySectionsTests(unittest.TestCase):
    # 准备当前测试所需的环境和数据。
    def setUp(self) -> None:
        """准备当前测试所需的环境和数据。"""
        self.temp_dir = DESKTOP_PET_ROOT / "tmp_work" / self._testMethodName
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.character_path = self.temp_dir / "character.json"
        self.safety_path = self.temp_dir / "safety.json"
        self.memory_path = self.temp_dir / "memory.json"
        self.summary_formal_path = self.temp_dir / "summary_formal.json"
        self.summary_informal_path = self.temp_dir / "summary_informal.json"
        self.config_path = self.temp_dir / "app_config.json"

        save_json(
            self.character_path,
            {
                "name": "小虎",
                "role": "桌面陪伴小伙伴",
                "personality": ["温柔"],
                "speaking_style": {
                    "daily_chat": "自然简短。",
                    "knowledge_answer": "清晰说明。",
                    "catchphrases": [],
                },
                "custom_prompt": "",
            },
        )
        save_json(self.safety_path, {"rules": ["安全第一。"]})
        save_json(self.summary_formal_path, {"summary": "", "highlights": []})
        save_json(self.summary_informal_path, {"summary": "", "highlights": []})
        save_json(
            self.config_path,
            {
                "api": {
                    "max_prompt_chars": 12000,
                    "max_history_messages": 12,
                    "max_user_message_chars": 1200,
                    "max_history_message_chars": 600,
                    "max_summary_chars": 1200,
                    "max_memory_chars": 1200,
                    "max_mem0_chars": 1000,
                    "summary_max_input_chars": 5000,
                    "memory_extract_max_input_chars": 3500,
                }
            },
        )
        save_json(
            self.memory_path,
            {
                "work_study": {"current_learning_topics": ["桌宠记忆系统"]},
                "relationship_memory": {
                    "communication_style": {
                        "preferred_response_style": "direct_actionable",
                        "confirmation_preference": "avoid_unnecessary_confirmation",
                    },
                    "companionship_style": {
                        "avoid_behaviors": ["避免机械化记忆表达"],
                    },
                },
            },
        )

    # 为测试准备builder数据或断言辅助结果。
    def _builder(self) -> PromptBuilder:
        """为测试准备builder数据或断言辅助结果。"""
        return PromptBuilder(
            self.character_path,
            self.safety_path,
            self.memory_path,
            self.summary_formal_path,
            self.summary_informal_path,
            self.config_path,
        )

    # 验证提示词会分离事实、关系和语义记忆段落。
    def test_build_messages_splits_fact_relationship_and_semantic_memory_sections(self) -> None:
        """验证提示词会分离事实、关系和语义记忆段落。"""
        messages = self._builder().build_messages(
            "这个功能怎么做？",
            relevant_memories="- 用户在开发桌宠。",
        )
        prompt = "\n".join(item["content"] for item in messages if item["role"] == "system")

        self.assertIn("【用户事实记忆】", prompt)
        self.assertIn("桌宠记忆系统", prompt)
        self.assertIn("【相处方式记忆】", prompt)
        self.assertIn("direct_actionable", prompt)
        self.assertIn("不要直接复述给用户", prompt)
        self.assertIn("不要频繁使用“你之前说过”", prompt)
        self.assertIn("【当前问题相关的长期语义记忆】", prompt)
        self.assertIn("只在与当前问题直接相关时参考", prompt)

    # 验证正式问答 模式 keeps style 记忆 focused on answer preferences场景下的预期结果。
    def test_formal_mode_keeps_style_memory_focused_on_answer_preferences(self) -> None:
        """验证正式问答 模式 keeps style 记忆 focused on answer preferences场景下的预期结果。"""
        messages = self._builder().build_messages("请解释这个架构。", formal_qa_mode=True)
        prompt = "\n".join(item["content"] for item in messages if item["role"] == "system")

        self.assertIn("当前处于正式问答模式", prompt)
        self.assertIn("【用户事实记忆】", prompt)
        self.assertIn("【相处方式记忆】", prompt)
        self.assertIn("优先保证回答准确、结构清晰、可执行", prompt)
        self.assertIn("角色风格不能降低专业性", prompt)
        self.assertNotIn("陪伴角色", prompt)

    # 验证new 人格 sections are compiled into executable guidance场景下的预期结果。
    def test_new_persona_sections_are_compiled_into_executable_guidance(self) -> None:
        """验证new 人格 sections are compiled into executable guidance场景下的预期结果。"""
        save_json(
            self.character_path,
            {
                "name": "小虎",
                "role": "桌面小伙伴",
                "core_identity": {
                    "summary": "安静可靠的桌面陪伴角色。",
                    "motivation": "低打扰地帮助用户推进事情。",
                },
                "personality_core": {
                    "stable_traits": ["细腻", "可靠", "有边界感"],
                    "not_traits": ["不过度撒娇", "不假装真人"],
                },
                "speaking_style": {
                    "default": "自然简短。",
                    "task_mode": "直接、清晰、结构化。",
                    "emotional_mode": "先承接情绪，再给一个小步骤。",
                    "avoid": ["空泛鼓励"],
                    "catchphrases": ["我在这里。"],
                },
                "behavior_policy": {
                    "proactive_style": "低频出现，不要求回应。",
                    "memory_usage": "只在直接相关时参考。",
                    "boundary": "不制造依赖。",
                },
                "scenario_reactions": {
                    "user_coding": "优先定位问题。",
                    "user_silent_long_time": "不追问。",
                },
            },
        )

        messages = self._builder().build_messages(
            "帮我看看代码。",
            runtime_persona_state={
                "mood": "thinking",
                "energy": "high",
                "closeness": 9,
                "mode": "task",
            },
        )
        prompt = "\n".join(item["content"] for item in messages if item["role"] == "system")

        self.assertIn("角色定位：安静可靠的桌面陪伴角色", prompt)
        self.assertIn("- 普通陪伴：自然简短", prompt)
        self.assertIn("- 任务协助：直接、清晰、结构化", prompt)
        self.assertIn("- 情绪安抚：先承接情绪", prompt)
        self.assertIn("不过度撒娇、不假装真人", prompt)
        self.assertIn("代码任务时优先定位问题", prompt)
        self.assertIn("mood=thinking, energy=high, mode=task", prompt)
        self.assertNotIn('"core_identity"', prompt)

    # 验证legacy character fields still build a complete 提示词场景下的预期结果。
    def test_legacy_character_fields_still_build_a_complete_prompt(self) -> None:
        """验证legacy character fields still build a complete 提示词场景下的预期结果。"""
        save_json(
            self.character_path,
            {
                "name": "旧角色",
                "role": "旧版桌面伙伴",
                "personality": ["温柔", "可靠"],
                "speech_style": "简短直接。",
                "catchphrases": ["慢慢来。"],
                "custom_prompt": "保持事实准确。",
            },
        )

        messages = self._builder().build_messages("你好")
        prompt = "\n".join(item["content"] for item in messages if item["role"] == "system")

        self.assertIn("你是旧角色", prompt)
        self.assertIn("稳定人格底色：温柔、可靠", prompt)
        self.assertIn("- 普通陪伴：简短直接", prompt)
        self.assertIn("口头禅只能偶尔自然使用：慢慢来", prompt)
        self.assertIn("保持事实准确", prompt)

    # 验证正式问答 模式 omits catchphrases and uses 任务 style场景下的预期结果。
    def test_formal_mode_omits_catchphrases_and_uses_task_style(self) -> None:
        """验证正式问答 模式 omits catchphrases and uses 任务 style场景下的预期结果。"""
        save_json(
            self.character_path,
            {
                "name": "小虎",
                "role": "桌面伙伴",
                "personality": ["可爱"],
                "speaking_style": {
                    "daily_chat": "软萌聊天。",
                    "knowledge_answer": "专业、清晰、结构化。",
                    "catchphrases": ["好哒～"],
                },
            },
        )

        messages = self._builder().build_messages("解释架构", formal_qa_mode=True)
        prompt = "\n".join(item["content"] for item in messages if item["role"] == "system")

        self.assertIn("- 任务协助：专业、清晰、结构化", prompt)
        self.assertNotIn("好哒～", prompt)
        self.assertIn("减少闲聊、口头禅、撒娇", prompt)

    # 验证long 用户 消息 is clipped by 预算场景下的预期结果。
    def test_long_user_message_is_clipped_by_budget(self) -> None:
        """验证long 用户 消息 is clipped by 预算场景下的预期结果。"""
        save_json(self.config_path, {"api": {"max_user_message_chars": 80}})
        messages = self._builder().build_messages("A" * 200, [])

        self.assertEqual("user", messages[-1]["role"])
        self.assertLessEqual(len(messages[-1]["content"]), 80)
        self.assertTrue(messages[-1]["content"].endswith("..."))

    # 验证long 历史记录 and 记忆 do not exceed 提示词 预算场景下的预期结果。
    def test_long_history_and_memory_do_not_exceed_prompt_budget(self) -> None:
        """验证long 历史记录 and 记忆 do not exceed 提示词 预算场景下的预期结果。"""
        save_json(
            self.config_path,
            {
                "api": {
                    "max_prompt_chars": 900,
                    "max_history_messages": 10,
                    "max_user_message_chars": 200,
                    "max_history_message_chars": 200,
                    "max_summary_chars": 300,
                    "max_memory_chars": 220,
                    "max_mem0_chars": 150,
                }
            },
        )
        save_json(self.summary_informal_path, {"summary": "S" * 1000, "highlights": []})
        save_json(
            self.memory_path,
            {
                "user_profile": {
                    "preferences": ["P" * 300, "Q" * 300],
                    "important_personal_notes": ["N" * 300],
                },
                "work_study": {"current_learning_topics": ["T" * 300]},
                "relationship_memory": {
                    "communication_style": {
                        "preferred_response_style": "direct_actionable",
                        "avoid_styles": ["M" * 200],
                    }
                },
            },
        )

        recent_messages = [
            {"role": "user", "content": f"user-{index}-" + ("U" * 300)}
            for index in range(8)
        ] + [
            {"role": "assistant", "content": f"assistant-{index}-" + ("A" * 300)}
            for index in range(8)
        ]
        messages = self._builder().build_messages(
            "当前问题：" + ("X" * 200),
            recent_messages,
            relevant_memories="\n".join([f"- mem0-{idx}-" + ("M" * 200) for idx in range(8)]),
        )

        total_chars = sum(len(item["content"]) for item in messages)
        self.assertLessEqual(total_chars, 900)
        self.assertEqual("user", messages[-1]["role"])

    # 验证tiny 提示词 预算 is still enforced场景下的预期结果。
    def test_tiny_prompt_budget_is_still_enforced(self) -> None:
        """验证tiny 提示词 预算 is still enforced场景下的预期结果。"""
        save_json(
            self.config_path,
            {
                "api": {
                    "max_prompt_chars": 240,
                    "max_history_messages": 4,
                    "max_user_message_chars": 120,
                    "max_history_message_chars": 120,
                }
            },
        )

        messages = self._builder().build_messages(
            "当前问题：" + ("X" * 200),
            [{"role": "assistant", "content": "A" * 300}],
        )

        self.assertLessEqual(sum(len(item["content"]) for item in messages), 240)

    # 验证missing 预算 配置 uses defaults场景下的预期结果。
    def test_missing_budget_config_uses_defaults(self) -> None:
        """验证missing 预算 配置 uses defaults场景下的预期结果。"""
        save_json(self.config_path, {"api": {}})
        messages = self._builder().build_messages("你好", [{"role": "assistant", "content": "A" * 50}])

        self.assertTrue(messages)
        self.assertEqual("你好", messages[-1]["content"])


class PersonaStateTests(unittest.TestCase):
    # 验证defaults are stable场景下的预期结果。
    def test_defaults_are_stable(self) -> None:
        """验证defaults are stable场景下的预期结果。"""
        state = read_persona_state()

        self.assertEqual(state.mood, EmotionState.CALM)
        self.assertEqual(state.energy, "normal")
        self.assertEqual(state.closeness, 0.5)
        self.assertEqual(state.mode, "companion")

    # 验证invalid values fall back and closeness is clamped场景下的预期结果。
    def test_invalid_values_fall_back_and_closeness_is_clamped(self) -> None:
        """验证invalid values fall back and closeness is clamped场景下的预期结果。"""
        state = PersonaState.from_mapping(
            {
                "mood": "unknown",
                "energy": "extreme",
                "closeness": 8,
                "mode": "unsupported",
            }
        )

        self.assertEqual(state.mood, EmotionState.CALM)
        self.assertEqual(state.energy, "normal")
        self.assertEqual(state.closeness, 1.0)
        self.assertEqual(state.mode, "companion")

    # 验证情绪 parser accepts enum or 文本 without raising场景下的预期结果。
    def test_emotion_parser_accepts_enum_or_text_without_raising(self) -> None:
        """验证情绪 parser accepts enum or 文本 without raising场景下的预期结果。"""
        self.assertEqual(parse_emotion_state("sleepy"), EmotionState.SLEEPY)
        self.assertEqual(parse_emotion_state(EmotionState.HAPPY), EmotionState.HAPPY)
        self.assertEqual(parse_emotion_state(None), EmotionState.CALM)


if __name__ == "__main__":
    unittest.main()
