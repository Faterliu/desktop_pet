from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from character.proactive_context import (  # noqa: E402
    build_local_scenario_greeting,
    build_proactive_context,
    build_scenario_greeting_messages,
    has_scenario_context,
    select_weighted_task_focus,
)


class ProactiveContextTests(unittest.TestCase):
    # 验证build 上下文 uses 任务 and relationship 记忆 without full dump场景下的预期结果。
    def test_build_context_uses_task_and_relationship_memory_without_full_dump(self) -> None:
        """验证build 上下文 uses 任务 and relationship 记忆 without full dump场景下的预期结果。"""
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
            character={
                "behavior_policy": {
                    "proactive_style": "低频、轻量，不要求回应。",
                    "memory_usage": "只在直接相关时参考。",
                    "boundary": "不制造依赖。",
                },
                "scenario_reactions": {
                    "user_silent_long_time": "不追问，也不责怪。",
                },
            },
        )

        self.assertEqual(context["time_period"], "afternoon")
        self.assertCountEqual(
            context["recent_task_focus"],
            ["桌宠记忆系统", "Mem0 接入", "很久以前的旧任务", "Prompt 分区"],
        )
        self.assertEqual(
            context["communication_style"]["preferred_response_style"],
            "direct_actionable",
        )
        self.assertEqual(context["companionship_style"]["proactive_boundary"], "low_frequency_when_busy")
        self.assertEqual(
            context["character_behavior"]["proactive_style"],
            "低频、轻量，不要求回应。",
        )
        self.assertEqual(context["runtime_state"]["mood"], "calm")
        self.assertEqual(context["runtime_state"]["consecutive_unanswered"], 1)
        self.assertTrue(has_scenario_context(context, min_items=2))

    # 验证较早任务在同一次加权抽取中的权重更高。
    def test_weighted_task_focus_prefers_older_timestamp(self) -> None:
        """验证主动问候优先选择较早的任务记录。"""
        class HighestWeightRandom:
            def __init__(self) -> None:
                self.calls: list[tuple[list[str], list[float]]] = []

            def choices(
                self,
                population: list[str],
                *,
                weights: list[float],
                k: int,
            ) -> list[str]:
                self.calls.append((population, weights))
                return [population[weights.index(max(weights))]]

        memory = {
            "work_study": {
                "current_projects": {
                    "projects_1": {
                        "description": ["较新的项目"],
                        "timestamp": "2026-07-10T00:00:00+00:00",
                    },
                    "projects_2": {
                        "description": ["较早的项目"],
                        "timestamp": "2026-07-01T00:00:00+00:00",
                    },
                }
            }
        }
        chooser = HighestWeightRandom()

        topics = select_weighted_task_focus(
            memory,
            limit=2,
            rng=chooser,
            now=datetime(2026, 7, 11, tzinfo=timezone.utc),
        )

        first_topics, first_weights = chooser.calls[0]
        self.assertGreater(
            first_weights[first_topics.index("较早的项目")],
            first_weights[first_topics.index("较新的项目")],
        )
        self.assertEqual(topics[0], "较早的项目")

    # 验证缺失或异常时间戳的任务记忆仍可安全参与主动问候。
    def test_weighted_task_focus_tolerates_invalid_timestamps(self) -> None:
        """验证异常时间戳不会阻断主动问候上下文生成。"""
        memory = {
            "work_study": {
                "current_projects": {
                    "projects_1": {"description": ["异常时间任务"], "timestamp": "invalid"},
                },
                "current_learning_topics": ["旧格式学习主题"],
            }
        }

        context = build_proactive_context(memory)

        self.assertCountEqual(context["recent_task_focus"], ["异常时间任务", "旧格式学习主题"])

    # 验证存在短期任务关注时不再混入项目和学习主题。
    def test_task_focus_takes_priority_over_project_and_learning_topics(self) -> None:
        """验证短期任务关注独立作为主动问候主题。"""
        memory = {
            "relationship_memory": {
                "interaction_patterns": {"task_focus": ["短期任务"]},
            },
            "work_study": {
                "current_projects": ["长期项目"],
                "current_learning_topics": ["学习主题"],
            },
        }

        context = build_proactive_context(memory)

        self.assertEqual(context["recent_task_focus"], ["短期任务"])

    # 验证本地 template 问候 is short natural and not mechanical场景下的预期结果。
    def test_local_template_greeting_is_short_natural_and_not_mechanical(self) -> None:
        """验证本地 template 问候 is short natural and not mechanical场景下的预期结果。"""
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

    # 验证low interrupt template uses quiet 台词场景下的预期结果。
    def test_low_interrupt_template_uses_quiet_line(self) -> None:
        """验证low interrupt template uses quiet 台词场景下的预期结果。"""
        context = {"runtime_state": {"consecutive_unanswered": 3}}
        local_lines = {"low_interrupt": ["看你可能在忙，我先安静一会儿，需要我就点我。"]}

        line = build_local_scenario_greeting(
            context,
            local_lines,
            max_chars=80,
            greeting_type="low_interrupt_greeting",
        )

        self.assertEqual(line, "看你可能在忙，我先安静一会儿，需要我就点我。")

    # 验证API 提示词 for 场景 问候 hides 记忆 implementation场景下的预期结果。
    def test_api_prompt_for_scenario_greeting_hides_memory_implementation(self) -> None:
        """验证API 提示词 for 场景 问候 hides 记忆 implementation场景下的预期结果。"""
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
        self.assertIn("不要频繁引用长期记忆", prompt)
        self.assertIn("不制造依赖", prompt)
        self.assertIn("桌宠记忆系统", prompt)


if __name__ == "__main__":
    unittest.main()
