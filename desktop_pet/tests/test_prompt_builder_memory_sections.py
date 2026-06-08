from __future__ import annotations

import sys
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from ai.prompt_builder import PromptBuilder  # noqa: E402
from storage.json_store import save_json  # noqa: E402


class PromptBuilderMemorySectionsTests(unittest.TestCase):
    def setUp(self) -> None:
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

    def _builder(self) -> PromptBuilder:
        return PromptBuilder(
            self.character_path,
            self.safety_path,
            self.memory_path,
            self.summary_formal_path,
            self.summary_informal_path,
            self.config_path,
        )

    def test_build_messages_splits_fact_relationship_and_semantic_memory_sections(self) -> None:
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

    def test_formal_mode_keeps_style_memory_focused_on_answer_preferences(self) -> None:
        messages = self._builder().build_messages("请解释这个架构。", formal_qa_mode=True)
        prompt = "\n".join(item["content"] for item in messages if item["role"] == "system")

        self.assertIn("当前处于正式问答模式", prompt)
        self.assertIn("【用户事实记忆】", prompt)
        self.assertIn("【相处方式记忆】", prompt)
        self.assertIn("优先保证回答准确、结构清晰、可执行", prompt)
        self.assertNotIn("陪伴角色", prompt)

    def test_long_user_message_is_clipped_by_budget(self) -> None:
        save_json(self.config_path, {"api": {"max_user_message_chars": 80}})
        messages = self._builder().build_messages("A" * 200, [])

        self.assertEqual("user", messages[-1]["role"])
        self.assertLessEqual(len(messages[-1]["content"]), 80)
        self.assertTrue(messages[-1]["content"].endswith("..."))

    def test_long_history_and_memory_do_not_exceed_prompt_budget(self) -> None:
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

    def test_tiny_prompt_budget_is_still_enforced(self) -> None:
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

    def test_missing_budget_config_uses_defaults(self) -> None:
        save_json(self.config_path, {"api": {}})
        messages = self._builder().build_messages("你好", [{"role": "assistant", "content": "A" * 50}])

        self.assertTrue(messages)
        self.assertEqual("你好", messages[-1]["content"])


if __name__ == "__main__":
    unittest.main()
