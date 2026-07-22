from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from storage.json_store import load_json  # noqa: E402
from storage.memory_store import MemoryStore  # noqa: E402


class RecordingVectorStore:
    # 记录迁移后收到的规范记忆快照。
    def __init__(self) -> None:
        """初始化同步快照列表。"""
        self.snapshots: list[dict] = []

    def sync_memory(self, memory: dict) -> None:
        """保存一次同步调用的记忆快照。"""
        self.snapshots.append(memory)


class MemorySchemaTests(unittest.TestCase):
    # 准备当前测试所需的环境和数据。
    def setUp(self) -> None:
        """准备当前测试所需的环境和数据。"""
        self.temp_dir = DESKTOP_PET_ROOT / "tmp_work" / self._testMethodName
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.memory_path = self.temp_dir / "memory.json"

    # 验证load保留规范记录并补齐当前 schema 的缺失分区。
    def test_load_preserves_canonical_records_and_fills_schema(self) -> None:
        """验证load保留规范记录并补齐当前 schema 的缺失分区。"""
        self.memory_path.write_text(
            json.dumps(
                {
                    "user_profile": {
                        "preferences": {
                            "preferences_1": {
                                "description": ["喜欢简洁"],
                                "timestamp": "2026-01-02T03:04:05+00:00",
                            }
                        },
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        store = MemoryStore(self.memory_path)
        memory = store.load()

        self.assertEqual(
            memory["user_profile"]["preferences"]["preferences_1"]["timestamp"],
            "2026-01-02T03:04:05+00:00",
        )
        self.assertEqual(memory["memory_meta"]["schema_version"], 5)
        self.assertNotIn("last_updated", memory["memory_meta"])
        self.assertIn("relationship_memory", memory)
        self.assertIn("light_interests", memory["user_profile"])
        self.assertIn("comfort_preferences", memory["user_profile"])
        self.assertIn("companionship_style", memory["relationship_memory"])
        self.assertIn("interaction_patterns", memory["relationship_memory"])
        self.assertIn(
            "recent_positive_events",
            memory["relationship_memory"]["interaction_patterns"],
        )
        self.assertEqual(store.load(), memory)

    # 验证补齐 schema 写回后会立即同步规范记忆到向量索引。
    def test_load_schema_completion_syncs_canonical_memory_to_vector_store(self) -> None:
        """验证补齐 schema 写回后会立即同步规范记忆到向量索引。"""
        self.memory_path.write_text(
            json.dumps(
                {
                    "user_profile": {
                        "preferences": {
                            "preferences_1": {
                                "description": ["当前偏好"],
                                "timestamp": "2026-01-02T03:04:05+00:00",
                            }
                        }
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        vector_store = RecordingVectorStore()

        memory = MemoryStore(self.memory_path, vector_store).load()

        self.assertEqual(len(vector_store.snapshots), 1)
        self.assertEqual(
            memory["user_profile"]["preferences"]["preferences_1"]["description"],
            ["当前偏好"],
        )

    # 验证结构化操作写入关系记忆，并保存当前 schema。
    def test_structured_operations_save_relationship_schema(self) -> None:
        """验证结构化操作写入关系记忆，并保存当前 schema。"""
        MemoryStore(self.memory_path).apply_summary_operations(
            "formal",
            3,
            [
                {
                    "action": "add",
                    "field": "relationship_memory.communication_style.preferred_response_style",
                    "description": ["direct_actionable"],
                },
                {
                    "action": "add",
                    "field": "relationship_memory.communication_style.avoid_styles",
                    "description": ["机械化记忆表达"],
                },
            ],
        )

        saved = load_json(self.memory_path, {})
        self.assertEqual(saved["memory_meta"]["schema_version"], 5)
        communication_style = saved["relationship_memory"]["communication_style"]
        self.assertEqual(
            communication_style["preferred_response_style"]["preferred_response_style_1"]["description"],
            ["direct_actionable"],
        )
        self.assertEqual(
            communication_style["avoid_styles"]["avoid_styles_1"]["description"],
            ["机械化记忆表达"],
        )

    # 验证非规范记录不会被迁移为当前记录。
    def test_noncanonical_records_are_not_migrated(self) -> None:
        """验证非规范记录不会被迁移为当前记录。"""
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

        self.assertEqual(memory["work_study"]["current_learning_topics"], {})

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
