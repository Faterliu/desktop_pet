from __future__ import annotations

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
        self.count = count

    def raise_for_status(self) -> None:
        return

    def json(self) -> dict[str, object]:
        return {
            "data": [
                {"index": index, "embedding": [1.0, float(index)]}
                for index in range(self.count)
            ]
        }


class FakeRequests:
    @staticmethod
    def post(*args, **kwargs):  # type: ignore[no-untyped-def]
        return FakeEmbeddingResponse(len(kwargs["json"]["input"]))


class MemoryVectorStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = DESKTOP_PET_ROOT / "tmp_work" / self._testMethodName
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.memory_path = self.temp_dir / "memory.json"
        self.vector_path = self.temp_dir / "memory_vectors.json"

    def test_memory_store_merge_generates_vectors_for_written_memory(self) -> None:
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

    def test_semantic_merge_removes_same_field_high_similarity_duplicate(self) -> None:
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
