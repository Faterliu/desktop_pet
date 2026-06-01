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
        save_json(
            self.character_path,
            {
                "name": "小胡",
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
            self.memory_path,
            {
                "work_study": {"current_learning_topics": ["桌宠记忆系统"]},
                "relationship_memory": {
                    "communication_style": {
                        "preferred_response_style": "direct_actionable",
                        "confirmation_preference": "avoid_unnecessary_confirmation",
                    },
                    "companionship_style": {
                        "avoid_behaviors": ["机械化记忆表达"],
                    },
                },
            },
        )

    def test_build_messages_splits_fact_relationship_and_semantic_memory_sections(self) -> None:
        builder = PromptBuilder(
            self.character_path,
            self.safety_path,
            self.memory_path,
            self.summary_formal_path,
            self.summary_informal_path,
        )

        messages = builder.build_messages(
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
        builder = PromptBuilder(
            self.character_path,
            self.safety_path,
            self.memory_path,
            self.summary_formal_path,
            self.summary_informal_path,
        )

        messages = builder.build_messages("请解释这个架构。", formal_qa_mode=True)
        prompt = "\n".join(item["content"] for item in messages if item["role"] == "system")

        self.assertIn("当前处于正式问答模式", prompt)
        self.assertIn("【用户事实记忆】", prompt)
        self.assertIn("【相处方式记忆】", prompt)
        self.assertIn("优先保证回答准确、结构清晰、可执行", prompt)
        self.assertNotIn("陪伴感表达", prompt)


if __name__ == "__main__":
    unittest.main()
