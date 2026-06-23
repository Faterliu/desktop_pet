from __future__ import annotations

import sys
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from storage.json_store import load_json  # noqa: E402


class ScenarioGreetingConfigTests(unittest.TestCase):
    def test_example_config_contains_conservative_scenario_greeting_defaults(self) -> None:
        """验证 `test_example_config_contains_conservative_scenario_greeting_defaults` 对应的行为。"""
        config = load_json(DESKTOP_PET_ROOT / "config" / "app_config.example.json", {})
        behavior = config["behavior"]

        self.assertTrue(behavior["enable_scenario_greeting"])
        self.assertTrue(behavior["scenario_greeting_api_enabled"])
        self.assertEqual(behavior["scenario_greeting_max_chars"], 80)
        self.assertEqual(behavior["scenario_greeting_min_memory_items"], 1)
        self.assertGreaterEqual(behavior["scenario_greeting_cooldown_minutes"], 60)
        self.assertEqual(behavior["scenario_greeting_low_interrupt_after_ignored"], 2)

    def test_local_lines_contains_scenario_and_low_interrupt_fallbacks(self) -> None:
        """验证 `test_local_lines_contains_scenario_and_low_interrupt_fallbacks` 对应的行为。"""
        local_lines = load_json(DESKTOP_PET_ROOT / "config" / "local_lines.json", {})

        self.assertTrue(local_lines["scenario_greeting_templates"])
        self.assertTrue(local_lines["low_interrupt"])
        self.assertIn("{task}", local_lines["scenario_greeting_templates"][0])


if __name__ == "__main__":
    unittest.main()
