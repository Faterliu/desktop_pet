from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from storage.json_store import load_json  # noqa: E402
from storage.memory_store import MemoryStore  # noqa: E402


class MemorySchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = DESKTOP_PET_ROOT / "tmp_work" / self._testMethodName
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.memory_path = self.temp_dir / "memory.json"

    def test_load_normalizes_old_memory_without_dropping_existing_fields(self) -> None:
        self.memory_path.write_text(
            json.dumps(
                {
                    "preferences": {"likes": ["直接的回答"]},
                    "user_profile": {"preferences": ["喜欢简洁"]},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        memory = MemoryStore(self.memory_path).load()

        self.assertEqual(memory["preferences"]["likes"], ["直接的回答"])
        self.assertEqual(memory["user_profile"]["preferences"], ["喜欢简洁"])
        self.assertEqual(memory["memory_meta"]["schema_version"], 2)
        self.assertIn("relationship_memory", memory)
        self.assertIn("communication_style", memory["relationship_memory"])
        self.assertIn("companionship_style", memory["relationship_memory"])
        self.assertIn("interaction_patterns", memory["relationship_memory"])

    def test_merge_preserves_old_memory_and_saves_relationship_schema(self) -> None:
        self.memory_path.write_text(
            json.dumps(
                {
                    "user_profile": {"preferences": ["喜欢简洁"]},
                    "work_study": {"current_projects": ["桌宠项目"]},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        MemoryStore(self.memory_path).merge(
            {
                "relationship_memory": {
                    "communication_style": {
                        "preferred_response_style": "direct_actionable",
                        "avoid_styles": ["机械化记忆表达"],
                    }
                }
            }
        )

        saved = load_json(self.memory_path, {})
        self.assertEqual(saved["user_profile"]["preferences"], ["喜欢简洁"])
        self.assertEqual(saved["work_study"]["current_projects"], ["桌宠项目"])
        self.assertEqual(saved["memory_meta"]["schema_version"], 2)
        communication_style = saved["relationship_memory"]["communication_style"]
        self.assertEqual(communication_style["preferred_response_style"], "direct_actionable")
        self.assertEqual(communication_style["avoid_styles"], ["机械化记忆表达"])


if __name__ == "__main__":
    unittest.main()
