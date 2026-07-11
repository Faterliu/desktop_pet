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

    # 验证load把旧版重复字段迁移到规范字段且不丢失描述。
    def test_load_migrates_legacy_memory_fields_to_canonical_paths(self) -> None:
        """验证旧版重复字段迁移、去重和元数据收敛。"""
        self.memory_path.write_text(
            json.dumps(
                {
                    "preferences": {"likes": ["直接的回答"]},
                    "user_profile": {
                        "preferences": ["喜欢简洁"],
                        "communication_style": {
                            "communication_style_1": {
                                "description": ["回答直接、可执行"],
                                "timestamp": "2026-01-02T03:04:05+00:00",
                            }
                        },
                    },
                    "memory_meta": {"last_updated": "legacy"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        store = MemoryStore(self.memory_path)
        memory = store.load()

        self.assertNotIn("preferences", memory)
        self.assertNotIn("communication_style", memory["user_profile"])
        self.assertCountEqual(
            [
                text
                for record in memory["user_profile"]["preferences"].values()
                for text in record["description"]
            ],
            ["喜欢简洁", "直接的回答"],
        )
        response_style = memory["relationship_memory"]["communication_style"][
            "preferred_response_style"
        ]
        self.assertEqual(
            response_style["preferred_response_style_1"]["description"],
            ["回答直接、可执行"],
        )
        self.assertEqual(
            response_style["preferred_response_style_1"]["timestamp"],
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

    # 验证迁移写回后会立即同步规范后的向量输入。
    def test_load_migration_syncs_canonical_memory_to_vector_store(self) -> None:
        """验证旧字段迁移不会让向量索引保留旧路径。"""
        self.memory_path.write_text(
            json.dumps({"preferences": ["旧版偏好"]}, ensure_ascii=False),
            encoding="utf-8",
        )
        vector_store = RecordingVectorStore()

        memory = MemoryStore(self.memory_path, vector_store).load()

        self.assertEqual(len(vector_store.snapshots), 1)
        self.assertNotIn("preferences", vector_store.snapshots[0])
        self.assertEqual(
            memory["user_profile"]["preferences"]["preferences_1"]["description"],
            ["旧版偏好"],
        )

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
