from __future__ import annotations

import logging
import shutil
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

logger_module = types.ModuleType("utils.logger")
logger_module.get_logger = logging.getLogger
sys.modules.setdefault("utils.logger", logger_module)

from storage.json_store import load_json, save_json  # noqa: E402
from storage.local_lines_service import LocalLinesService  # noqa: E402


class LocalLinesServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = DESKTOP_PET_ROOT / "tmp_work" / "test_local_lines_service" / self._testMethodName
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.lines_path = self.temp_dir / "local_lines.json"
        self.meta_path = self.temp_dir / "local_lines_generated_meta.json"

    def tearDown(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_pick_line_supports_existing_array_shape(self) -> None:
        save_json(self.lines_path, {"knowledge_speak_intro": ["一句话", "另一句话"]})
        service = LocalLinesService(self.lines_path)

        with patch("storage.local_lines_service.random.choice", side_effect=lambda items: items[0]):
            self.assertEqual(service.pick_line("knowledge_speak_intro"), "一句话")

    def test_pick_line_returns_fallback_for_missing_group(self) -> None:
        save_json(self.lines_path, {})
        service = LocalLinesService(self.lines_path)

        self.assertEqual(service.pick_line("missing", fallback="兜底"), "兜底")

    def test_replace_generated_lines_filters_bad_lines_and_records_metadata(self) -> None:
        save_json(self.lines_path, {"knowledge_speak_intro": ["人工话术"]})
        service = LocalLinesService(self.lines_path, self.meta_path)

        result = service.replace_generated_lines(
            "knowledge_speak_intro",
            [
                "新话术一",
                "新话术一",
                "",
                "根据记忆我想说一句话",
                "这句话太长了",
            ],
            source="deepseek",
            max_chars=5,
            max_items=5,
        )

        self.assertEqual(result.accepted, ["新话术一"])
        self.assertTrue(result.saved)
        self.assertEqual(load_json(self.lines_path, {})["knowledge_speak_intro"], ["人工话术", "新话术一"])
        metadata = load_json(self.meta_path, {})
        self.assertEqual(metadata["groups"]["knowledge_speak_intro"]["source"], "deepseek")
        self.assertEqual(metadata["groups"]["knowledge_speak_intro"]["count"], 1)

    def test_append_manual_line_dedupes_without_rewriting_existing_line(self) -> None:
        save_json(self.lines_path, {"idle": ["已有"]})
        service = LocalLinesService(self.lines_path)

        result = service.append_manual_line("idle", "已有")

        self.assertFalse(result.saved)
        self.assertEqual(load_json(self.lines_path, {})["idle"], ["已有"])

    def test_consume_first_start_line_disables_flag(self) -> None:
        save_json(self.lines_path, {"first_start": {"enable": True, "data": ["你好"]}})
        service = LocalLinesService(self.lines_path)

        self.assertEqual(service.consume_first_start_line(), "你好")
        self.assertFalse(load_json(self.lines_path, {})["first_start"]["enable"])


if __name__ == "__main__":
    unittest.main()
