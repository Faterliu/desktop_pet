from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from storage.json_store import load_json, save_json  # noqa: E402
from storage.memory_store import MemoryStore  # noqa: E402
from storage.memory_vector_store import MemoryVectorStore  # noqa: E402


class FakeEmbeddingResponse:
    def __init__(self, count: int) -> None:
        """初始化当前对象及其依赖。"""
        self.count = count

    def raise_for_status(self) -> None:
        """处理 `raise_for_status` 对应的业务逻辑。"""
        return

    def json(self) -> dict[str, object]:
        """处理 `json` 对应的业务逻辑。"""
        return {
            "data": [
                {"index": index, "embedding": [1.0, float(index)]}
                for index in range(self.count)
            ]
        }


class FakeRequests:
    @staticmethod
    def post(*args, **kwargs):  # type: ignore[no-untyped-def]
        """处理 `post` 对应的业务逻辑。"""
        return FakeEmbeddingResponse(len(kwargs["json"]["input"]))


class PreciseEmbeddingResponse:
    def __init__(self, count: int) -> None:
        """初始化当前对象及其依赖。"""
        self.count = count

    def raise_for_status(self) -> None:
        """处理 `raise_for_status` 对应的业务逻辑。"""
        return

    def json(self) -> dict[str, object]:
        """处理 `json` 对应的业务逻辑。"""
        return {
            "data": [
                {
                    "index": index,
                    "embedding": [
                        0.123456789 + index,
                        0.987654321 - index,
                    ],
                }
                for index in range(self.count)
            ]
        }


class PreciseFakeRequests:
    @staticmethod
    def post(*args, **kwargs):  # type: ignore[no-untyped-def]
        """处理 `post` 对应的业务逻辑。"""
        return PreciseEmbeddingResponse(len(kwargs["json"]["input"]))


class MemoryVectorStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        """准备当前测试所需的环境和数据。"""
        self.temp_dir = DESKTOP_PET_ROOT / "tmp_work" / self._testMethodName
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.memory_path = self.temp_dir / "memory.json"
        self.vector_path = self.temp_dir / "memory_vectors.json"

    def test_memory_store_merge_generates_vectors_for_written_memory(self) -> None:
        """验证 `test_memory_store_merge_generates_vectors_for_written_memory` 对应的行为。"""
        app_config = {
            "memory": {
                "enable_memory_vectors": True,
                "dashscope_api_key": "test-key",
                "dashscope_embedding_base_url": "https://dashscope.test/v1",
                "dashscope_embedding_model": "text-embedding-v4",
                "dashscope_embedding_dimensions": 2,
                "memory_embedding_batch_size": 8,
            }
        }
        vector_store = MemoryVectorStore(self.vector_path, app_config)
        memory_store = MemoryStore(self.memory_path, vector_store)

        with patch("storage.memory_vector_store.requests", FakeRequests):
            memory_store.merge(
                {
                    "user_profile": {
                        "preferences": ["喜欢简洁直接的回答"],
                    }
                }
            )

        index = load_json(self.vector_path, {})
        self.assertEqual(len(index["items"]), 1)
        self.assertEqual(index["items"][0]["text"], "喜欢简洁直接的回答")
        self.assertEqual(index["items"][0]["embedding"], [1.0, 0.0])

    def test_vector_index_is_compact_and_embeddings_are_rounded(self) -> None:
        """验证 `test_vector_index_is_compact_and_embeddings_are_rounded` 对应的行为。"""
        app_config = {
            "memory": {
                "enable_memory_vectors": True,
                "dashscope_api_key": "test-key",
                "dashscope_embedding_base_url": "https://dashscope.test/v1",
                "dashscope_embedding_model": "text-embedding-v4",
                "dashscope_embedding_dimensions": 2,
                "memory_vector_precision": 6,
                "memory_vector_min_text_length": 3,
            }
        }
        store = MemoryVectorStore(self.vector_path, app_config)
        memory = {
            "user_profile": {
                "preferences": ["first long memory text", "second long memory text"],
            }
        }

        with patch("storage.memory_vector_store.requests", PreciseFakeRequests):
            store.sync_memory(memory)

        raw = self.vector_path.read_text(encoding="utf-8")
        index = json.loads(raw)
        pretty = json.dumps(index, ensure_ascii=False, indent=2)

        self.assertLess(len(raw), int(len(pretty) * 0.8))
        self.assertEqual(index["items"][0]["embedding"], [0.123457, 0.987654])
        self.assertNotIn("\n  ", raw)

    def test_missing_vector_config_uses_defaults(self) -> None:
        """验证 `test_missing_vector_config_uses_defaults` 对应的行为。"""
        app_config = {
            "memory": {
                "enable_memory_vectors": True,
                "dashscope_api_key": "test-key",
                "dashscope_embedding_base_url": "https://dashscope.test/v1",
                "dashscope_embedding_model": "text-embedding-v4",
                "dashscope_embedding_dimensions": 2,
            }
        }
        store = MemoryVectorStore(self.vector_path, app_config)

        with patch("storage.memory_vector_store.requests", PreciseFakeRequests):
            store.sync_memory({"user_profile": {"preferences": ["abc"]}})

        index = load_json(self.vector_path, {})
        self.assertEqual(len(index["items"]), 1)
        self.assertEqual(index["items"][0]["embedding"], [0.123457, 0.987654])
        self.assertIn("precision=6", index["embedding_signature"])

    def test_short_texts_are_skipped(self) -> None:
        """验证 `test_short_texts_are_skipped` 对应的行为。"""
        app_config = {
            "memory": {
                "enable_memory_vectors": True,
                "dashscope_api_key": "test-key",
                "dashscope_embedding_base_url": "https://dashscope.test/v1",
                "dashscope_embedding_model": "text-embedding-v4",
                "dashscope_embedding_dimensions": 2,
                "memory_vector_min_text_length": 8,
            }
        }
        store = MemoryVectorStore(self.vector_path, app_config)

        with patch("storage.memory_vector_store.requests", FakeRequests):
            store.sync_memory({"user_profile": {"preferences": ["short", "long enough memory"]}})

        index = load_json(self.vector_path, {})
        self.assertEqual([item["text"] for item in index["items"]], ["long enough memory"])

    def test_old_signature_index_is_rebuilt_with_precision_signature(self) -> None:
        """验证 `test_old_signature_index_is_rebuilt_with_precision_signature` 对应的行为。"""
        save_json(
            self.vector_path,
            {
                "schema_version": "1.0",
                "embedding_signature": "old-signature",
                "last_synced_at": "",
                "last_semantic_merge_at": "",
                "items": [
                    self._vector_item(
                        MemoryVectorStore(self.vector_path, {"memory": {}}),
                        "user_profile.preferences",
                        "stale memory text",
                        0,
                        [9.0, 9.0],
                    )
                ],
            },
        )
        app_config = {
            "memory": {
                "enable_memory_vectors": True,
                "dashscope_api_key": "test-key",
                "dashscope_embedding_base_url": "https://dashscope.test/v1",
                "dashscope_embedding_model": "text-embedding-v4",
                "dashscope_embedding_dimensions": 2,
                "memory_vector_precision": 4,
            }
        }
        store = MemoryVectorStore(self.vector_path, app_config)

        with patch("storage.memory_vector_store.requests", PreciseFakeRequests):
            store.sync_memory({"user_profile": {"preferences": ["fresh memory text"]}})

        index = load_json(self.vector_path, {})
        self.assertEqual([item["text"] for item in index["items"]], ["fresh memory text"])
        self.assertEqual(index["items"][0]["embedding"], [0.1235, 0.9877])
        self.assertIn("precision=4", index["embedding_signature"])

    def test_vector_index_keeps_max_items_by_recent_or_important_memory(self) -> None:
        """验证 `test_vector_index_keeps_max_items_by_recent_or_important_memory` 对应的行为。"""
        app_config = {
            "memory": {
                "enable_memory_vectors": True,
                "dashscope_api_key": "test-key",
                "dashscope_embedding_base_url": "https://dashscope.test/v1",
                "dashscope_embedding_model": "text-embedding-v4",
                "dashscope_embedding_dimensions": 2,
                "memory_vector_max_items": 2,
                "memory_vector_min_text_length": 3,
            }
        }
        store = MemoryVectorStore(self.vector_path, app_config)
        memory = {
            "user_profile": {
                "preferences": ["older preference memory"],
            },
            "work_study": {
                "current_projects": ["important project memory"],
                "useful_context": ["ordinary context memory"],
            },
        }

        with patch("storage.memory_vector_store.requests", FakeRequests):
            store.sync_memory(memory)

        index = load_json(self.vector_path, {})
        texts = {item["text"] for item in index["items"]}
        self.assertEqual(len(texts), 2)
        self.assertIn("important project memory", texts)

    def test_semantic_merge_removes_same_field_high_similarity_duplicate(self) -> None:
        """验证 `test_semantic_merge_removes_same_field_high_similarity_duplicate` 对应的行为。"""
        memory = {
            "schema_version": "1.0",
            "user_profile": {
                "preferences": ["喜欢简短回答", "偏好简短直接的回答", "喜欢番茄"],
                "communication_style": [],
                "important_personal_notes": [],
            },
            "work_study": {
                "current_learning_topics": [],
                "current_projects": [],
                "useful_context": [],
            },
            "last_updated": "",
        }
        save_json(self.memory_path, memory)

        app_config = {
            "memory": {
                "semantic_duplicate_similarity_threshold": 0.96,
                "dashscope_api_key": "",
            }
        }
        store = MemoryVectorStore(self.vector_path, app_config)
        save_json(
            self.vector_path,
            {
                "schema_version": "1.0",
                "embedding_signature": "test",
                "last_synced_at": "",
                "last_semantic_merge_at": "",
                "items": [
                    self._vector_item(store, "user_profile.preferences", "喜欢简短回答", 0, [1.0, 0.0]),
                    self._vector_item(
                        store,
                        "user_profile.preferences",
                        "偏好简短直接的回答",
                        1,
                        [0.99, 0.01],
                    ),
                    self._vector_item(store, "user_profile.preferences", "喜欢番茄", 2, [0.0, 1.0]),
                ],
            },
        )

        result = store._merge_semantic_duplicates(self.memory_path)

        updated = load_json(self.memory_path, {})
        self.assertEqual(result["merged_count"], 1)
        self.assertEqual(
            updated["user_profile"]["preferences"],
            ["偏好简短直接的回答", "喜欢番茄"],
        )

    def test_semantic_merge_does_not_merge_across_memory_fields(self) -> None:
        """验证 `test_semantic_merge_does_not_merge_across_memory_fields` 对应的行为。"""
        memory = {
            "schema_version": "1.0",
            "user_profile": {
                "preferences": ["喜欢简短回答"],
                "communication_style": ["偏好简短直接的回答"],
                "important_personal_notes": [],
            },
            "work_study": {
                "current_learning_topics": [],
                "current_projects": [],
                "useful_context": [],
            },
            "last_updated": "",
        }
        save_json(self.memory_path, memory)

        store = MemoryVectorStore(self.vector_path, {"memory": {"semantic_duplicate_similarity_threshold": 0.96}})
        save_json(
            self.vector_path,
            {
                "schema_version": "1.0",
                "embedding_signature": "test",
                "last_synced_at": "",
                "last_semantic_merge_at": "",
                "items": [
                    self._vector_item(store, "user_profile.preferences", "喜欢简短回答", 0, [1.0, 0.0]),
                    self._vector_item(
                        store,
                        "user_profile.communication_style",
                        "偏好简短直接的回答",
                        1,
                        [0.99, 0.01],
                    ),
                ],
            },
        )

        result = store._merge_semantic_duplicates(self.memory_path)

        updated = load_json(self.memory_path, {})
        self.assertEqual(result["merged_count"], 0)
        self.assertEqual(updated["user_profile"]["preferences"], ["喜欢简短回答"])
        self.assertEqual(updated["user_profile"]["communication_style"], ["偏好简短直接的回答"])

    def _vector_item(
        self,
        store: MemoryVectorStore,
        path: str,
        text: str,
        order: int,
        embedding: list[float],
    ) -> dict[str, object]:
        """处理 `_vector_item` 对应的业务逻辑。"""
        return {
            "id": store._item_id(path, text),
            "path": path,
            "text": text,
            "order": order,
            "embedding": embedding,
            "updated_at": "",
        }


if __name__ == "__main__":
    unittest.main()
