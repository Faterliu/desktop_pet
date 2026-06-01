from __future__ import annotations

import sys
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from character.proactive_context import (  # noqa: E402
    build_local_scenario_greeting,
    build_proactive_context,
    build_scenario_greeting_messages,
    has_scenario_context,
)


class ProactiveContextTests(unittest.TestCase):
    def test_build_context_uses_task_and_relationship_memory_without_full_dump(self) -> None:
        memory = {
            "work_study": {
                "current_projects": ["桌宠记忆系统", "Mem0 接入", "很久以前的旧任务"],
                "current_learning_topics": ["Prompt 分区"],
            },
            "relationship_memory": {
                "communication_style": {
                    "preferred_response_style": "direct_actionable",
                    "detail_level": "high",
                    "confirmation_preference": "avoid_unnecessary_confirmation",
                },
                "companionship_style": {
                    "proactive_boundary": "low_frequency_when_busy",
                    "encouragement_style": "specific_and_low_pressure",
                    "avoid_behaviors": ["机械化记忆表达"],
                },
                "interaction_patterns": {
                    "recent_interaction_mode": "focused_work",
                    "interruption_tolerance": "low",
                },
            },
        }

        context = build_proactive_context(
            memory,
            runtime_state={"consecutive_unanswered": 1, "last_proactive_type": "regular_greeting"},
            time_period="afternoon",
            season="summer",
        )

        self.assertEqual(context["time_period"], "afternoon")
        self.assertEqual(context["recent_task_focus"][:2], ["桌宠记忆系统", "Mem0 接入"])
        self.assertEqual(
            context["communication_style"]["preferred_response_style"],
            "direct_actionable",
        )
        self.assertEqual(context["companionship_style"]["proactive_boundary"], "low_frequency_when_busy")
        self.assertTrue(has_scenario_context(context, min_items=2))

    def test_local_template_greeting_is_short_natural_and_not_mechanical(self) -> None:
        context = {
            "recent_task_focus": ["桌宠记忆系统"],
            "runtime_state": {"consecutive_unanswered": 0},
        }
        local_lines = {
            "scenario_greeting_templates": [
                "你最近好像主要在推进{task}，要不要先从最关键的一小步开始？"
            ]
        }

        line = build_local_scenario_greeting(
            context,
            local_lines,
            max_chars=80,
            greeting_type="memory_context_greeting",
        )

        self.assertIn("桌宠记忆系统", line)
        self.assertLessEqual(len(line), 80)
        self.assertNotIn("根据记忆", line)
        self.assertNotIn("你之前说过", line)
        self.assertNotIn("memory.json", line)

    def test_low_interrupt_template_uses_quiet_line(self) -> None:
        context = {"runtime_state": {"consecutive_unanswered": 3}}
        local_lines = {"low_interrupt": ["看你可能在忙，我先安静一会儿，需要我就点我。"]}

        line = build_local_scenario_greeting(
            context,
            local_lines,
            max_chars=80,
            greeting_type="low_interrupt_greeting",
        )

        self.assertEqual(line, "看你可能在忙，我先安静一会儿，需要我就点我。")

    def test_api_prompt_for_scenario_greeting_hides_memory_implementation(self) -> None:
        context = {
            "time_period": "afternoon",
            "recent_task_focus": ["桌宠记忆系统"],
            "communication_style": {"preferred_response_style": "direct_actionable"},
            "companionship_style": {"proactive_boundary": "low_frequency_when_busy"},
            "runtime_state": {"consecutive_unanswered": 1},
        }

        messages = build_scenario_greeting_messages(context, max_chars=60)
        prompt = "\n".join(item["content"] for item in messages)

        self.assertIn("只输出一句中文", prompt)
        self.assertIn("不要超过 60 个中文字符", prompt)
        self.assertIn("不要说“根据记忆”", prompt)
        self.assertIn("不要暴露 memory.json、Mem0、数据库、配置等技术细节", prompt)
        self.assertIn("桌宠记忆系统", prompt)


if __name__ == "__main__":
    unittest.main()
