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
    # 准备当前测试所需的环境和数据。
    def setUp(self) -> None:
        """准备当前测试所需的环境和数据。"""
        self.temp_dir = DESKTOP_PET_ROOT / "tmp_work" / self._testMethodName
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.memory_path = self.temp_dir / "memory.json"

    # 验证load normalizes old 记忆 without dropping existing fields场景下的预期结果。
    def test_load_normalizes_old_memory_without_dropping_existing_fields(self) -> None:
        """验证load normalizes old 记忆 without dropping existing fields场景下的预期结果。"""
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
        self.assertEqual(
            memory["user_profile"]["preferences"]["preferences_1"]["description"],
            ["喜欢简洁"],
        )
        self.assertEqual(memory["memory_meta"]["schema_version"], 3)
        self.assertIn("relationship_memory", memory)
        self.assertIn("communication_style", memory["relationship_memory"])
        self.assertIn("companionship_style", memory["relationship_memory"])
        self.assertIn("interaction_patterns", memory["relationship_memory"])

    # 验证merge preserves old 记忆 and saves relationship schema场景下的预期结果。
    def test_merge_preserves_old_memory_and_saves_relationship_schema(self) -> None:
        """验证merge preserves old 记忆 and saves relationship schema场景下的预期结果。"""
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
        self.assertEqual(
            saved["user_profile"]["preferences"]["preferences_1"]["description"],
            ["喜欢简洁"],
        )
        self.assertEqual(
            saved["work_study"]["current_projects"]["projects_1"]["description"],
            ["桌宠项目"],
        )
        self.assertEqual(saved["memory_meta"]["schema_version"], 3)
        communication_style = saved["relationship_memory"]["communication_style"]
        self.assertEqual(
            communication_style["preferred_response_style"]["preferred_response_style_1"]["description"],
            ["direct_actionable"],
        )
        self.assertEqual(
            communication_style["avoid_styles"]["avoid_styles_1"]["description"],
            ["机械化记忆表达"],
        )

    # 验证旧 data 时间字段被迁移为带时区的 timestamp。
    def test_legacy_record_data_timestamp_is_migrated(self) -> None:
        """验证旧 data 时间字段被迁移为带时区的 timestamp。"""
        self.memory_path.write_text(
            json.dumps(
                {
                    "work_study": {
                        "current_learning_topics": {
                            "topics_1": {
                                "description": ["旧学习主题"],
                                "data": "2026-06-23T11:29:13",
                            }
                        }
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        memory = MemoryStore(self.memory_path).load()
        record = memory["work_study"]["current_learning_topics"]["topics_1"]

        self.assertEqual(record["description"], ["旧学习主题"])
        self.assertIn("+00:00", record["timestamp"])
        self.assertNotIn("data", record)

    # 验证程序分配连续编号、更新保留编号并刷新时间戳。
    def test_operations_allocate_and_update_numbered_records(self) -> None:
        """验证程序分配连续编号、更新保留编号并刷新时间戳。"""
        store = MemoryStore(self.memory_path)
        store.apply_summary_operations(
            "formal",
            3,
            [
                {
                    "action": "add",
                    "field": "work_study.current_learning_topics",
                    "description": ["主题一"],
                },
                {
                    "action": "add",
                    "field": "work_study.current_learning_topics",
                    "description": ["主题二"],
                },
            ],
        )
        before = store.load()["work_study"]["current_learning_topics"]["topics_1"]["timestamp"]
        store.apply_summary_operations(
            "formal",
            6,
            [
                {
                    "action": "update",
                    "field": "work_study.current_learning_topics",
                    "record_id": "topics_1",
                    "description": ["合并后的主题一"],
                },
                {
                    "action": "unchanged",
                    "field": "work_study.current_learning_topics",
                },
            ],
        )

        records = store.load()["work_study"]["current_learning_topics"]
        self.assertEqual(sorted(records), ["topics_1", "topics_2"])
        self.assertEqual(records["topics_1"]["description"], ["合并后的主题一"])
        self.assertGreaterEqual(records["topics_1"]["timestamp"], before)
        self.assertEqual(store.load()["memory_meta"]["summary_batches"]["formal"], 6)


if __name__ == "__main__":
    unittest.main()
