from __future__ import annotations

import sys
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from app.config_service import ConfigService  # noqa: E402


class ConfigServiceTests(unittest.TestCase):
    def test_get_returns_nested_values_and_defaults(self) -> None:
        service = ConfigService(
            {
                "api": {"enabled": True, "timeout": "12"},
                "ui": {"scale": 1.25},
            }
        )

        self.assertTrue(service.get("api.enabled", False))
        self.assertEqual(service.get("ui.scale", 1.0), 1.25)
        self.assertEqual(service.get("api.missing", "fallback"), "fallback")
        self.assertEqual(service.get("api.timeout.seconds", 5), 5)

    def test_typed_getters_are_safe_for_missing_and_invalid_values(self) -> None:
        service = ConfigService(
            {
                "feature": {"enabled": 1},
                "numbers": {"valid": "42", "invalid": "x"},
                "text": {"value": 123, "none": None},
            }
        )

        self.assertTrue(service.get_bool("feature.enabled", False))
        self.assertFalse(service.get_bool("feature.missing", False))
        self.assertEqual(service.get_int("numbers.valid", 0), 42)
        self.assertEqual(service.get_int("numbers.invalid", 7), 7)
        self.assertEqual(service.get_int("numbers.missing", 9), 9)
        self.assertEqual(service.get_str("text.value", ""), "123")
        self.assertEqual(service.get_str("text.none", "fallback"), "fallback")

    def test_update_points_to_new_config(self) -> None:
        service = ConfigService({"ui": {"always_on_top": True}})

        service.update({"ui": {"always_on_top": False}})

        self.assertFalse(service.get_bool("ui.always_on_top", True))

    def test_empty_config_keeps_original_mapping_reference(self) -> None:
        config: dict[str, object] = {}
        service = ConfigService(config)

        config["ui"] = {"always_on_top": False}

        self.assertFalse(service.get_bool("ui.always_on_top", True))


if __name__ == "__main__":
    unittest.main()
