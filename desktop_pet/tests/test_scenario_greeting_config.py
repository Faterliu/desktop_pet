from __future__ import annotations

import sys
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from storage.json_store import load_json  # noqa: E402


class ScenarioGreetingConfigTests(unittest.TestCase):
    # 验证example 配置 contains conservative 场景 问候 defaults场景下的预期结果。
    def test_example_config_contains_conservative_scenario_greeting_defaults(self) -> None:
        """验证example 配置 contains conservative 场景 问候 defaults场景下的预期结果。"""
        config = load_json(DESKTOP_PET_ROOT / "config" / "app_config.example.json", {})
        behavior = config["behavior"]

        self.assertTrue(behavior["enable_scenario_greeting"])
        self.assertTrue(behavior["scenario_greeting_api_enabled"])
        self.assertEqual(behavior["scenario_greeting_max_chars"], 80)
        self.assertEqual(behavior["scenario_greeting_min_memory_items"], 1)
        self.assertGreaterEqual(behavior["scenario_greeting_cooldown_minutes"], 60)
        self.assertEqual(behavior["scenario_greeting_low_interrupt_after_ignored"], 2)

    # 验证本地 台词 contains 场景 and low interrupt fallbacks场景下的预期结果。
    def test_local_lines_contains_scenario_and_low_interrupt_fallbacks(self) -> None:
        """验证本地 台词 contains 场景 and low interrupt fallbacks场景下的预期结果。"""
        local_lines = load_json(DESKTOP_PET_ROOT / "config" / "local_lines.json", {})

        self.assertTrue(local_lines["scenario_greeting_templates"])
        self.assertTrue(local_lines["low_interrupt"])
        self.assertEqual(len(local_lines["scenario_greeting_templates"]), 3)
        self.assertTrue(
            all("{task}" in line for line in local_lines["scenario_greeting_templates"])
        )

    # 验证从场景模板移出的时间话术进入对应时段分组。
    def test_time_lines_are_moved_to_matching_groups(self) -> None:
        """验证早晨、中午、下午、傍晚和深夜话术归类正确。"""
        local_lines = load_json(DESKTOP_PET_ROOT / "config" / "local_lines.json", {})

        expected = {
            "greeting_morning": "早上好呀，今天也陪你慢慢进入状态。",
            "greeting_noon": "午休到啦，记得伸个懒腰放松一下。",
            "greeting_afternoon": "午后好，记得给自己留一点休息时间",
            "greeting_evening": "傍晚好，天边染了橘色，我也陪你看一会儿日落。",
            "sleepy": "夜深了，要是还不想睡，我就在桌角轻轻陪着你。",
        }
        for group, line in expected.items():
            with self.subTest(group=group):
                self.assertIn(line, local_lines[group])

    # 验证关闭全局置顶的话术不会误称为关闭某条通知。
    def test_ignored_lines_do_not_describe_a_single_notification(self) -> None:
        """验证 ignored 只描述人物窗口退出置顶状态。"""
        local_lines = load_json(DESKTOP_PET_ROOT / "config" / "local_lines.json", {})
        removed_lines = {
            "好呀，这条提示先不置顶啦",
            "收到，之后不再反复提醒这件事",
            "明白啦，我会让这条提示安静待着",
            "好的，这条内容先不打扰你啦",
            "知道啦，我不会再把它置顶提醒",
            "没问题，之后就不主动弹出这条提示啦",
            "好哒，这条提示先轻轻放下",
            "收到，我会减少这条提示的出现",
        }

        self.assertTrue(removed_lines.isdisjoint(local_lines["ignored"]))


if __name__ == "__main__":
    unittest.main()
