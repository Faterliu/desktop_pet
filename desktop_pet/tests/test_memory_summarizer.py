from __future__ import annotations

import json
import shutil
import sys
import types
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))
sys.modules.setdefault(
    "requests",
    types.SimpleNamespace(Timeout=RuntimeError, RequestException=RuntimeError, post=lambda *args, **kwargs: None),
)

from ai.memory_summarizer import MemorySummarizer  # noqa: E402
from storage.memory_store import MemoryStore  # noqa: E402


class MemoryClient:
    # 初始化记录模型请求的测试客户端。
    def __init__(self, fail: bool = False) -> None:
        """初始化记录模型请求的测试客户端。"""
        self.fail = fail
        self.messages: list[list[dict[str, str]]] = []

    # 为测试声明客户端已经配置。
    def is_configured(self) -> bool:
        """为测试声明客户端已经配置。"""
        return True

    # 返回完整的长期记忆 JSON，或模拟失败。
    def chat(self, messages: list[dict[str, str]]) -> str:
        """返回完整的长期记忆 JSON，或模拟失败。"""
        self.messages.append(messages)
        if self.fail:
            raise RuntimeError("network unavailable")
        return json.dumps(
            {
                "operations": [
                    {
                        "action": "add",
                        "field": "user_profile.preferences",
                        "description": ["喜欢简洁回答"],
                        "reason": "new",
                    }
                ],
                "conclusion": {"added": 1, "updated": 0, "unchanged": 0},
            },
            ensure_ascii=False,
        )


class InvalidOperationClient(MemoryClient):
    # 返回包含不允许字段的模型操作。
    def chat(self, messages: list[dict[str, str]]) -> str:
        """返回包含不允许字段的模型操作。"""
        self.messages.append(messages)
        return json.dumps(
            {
                "operations": [
                    {
                        "action": "add",
                        "field": "unsupported.field",
                        "description": ["不应写入"],
                    }
                ],
                "conclusion": {"added": 1, "updated": 0, "unchanged": 0},
            },
            ensure_ascii=False,
        )


class MemorySummarizerTests(unittest.TestCase):
    # 准备独立临时目录。
    def setUp(self) -> None:
        """准备独立临时目录。"""
        self.temp_dir = DESKTOP_PET_ROOT / "tmp_work" / "test_memory_summarizer" / self._testMethodName
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.memory_store = MemoryStore(self.temp_dir / "memory.json")
        self.entries = [
            {"sequence": index, "summary": f"摘要{index}", "highlights": []}
            for index in range(1, 4)
        ]

    # 清理临时目录。
    def tearDown(self) -> None:
        """清理临时目录。"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    # 验证只使用单一模式的三个摘要，并记录已完成批次。
    def test_batch_replaces_memory_and_marks_mode_sequence(self) -> None:
        """验证只使用单一模式的三个摘要，并记录已完成批次。"""
        client = MemoryClient()
        service = MemorySummarizer(self.memory_store, client, lambda: {"api": {}})  # type: ignore[arg-type]

        self.assertTrue(service.summarize_batch("clipboard", self.entries, 3))

        memory = self.memory_store.load()
        source = client.messages[0][-1]["content"]
        instructions = client.messages[0][0]["content"]
        self.assertIn("摘要1", source)
        self.assertIn("摘要3", source)
        self.assertIn("user_profile.light_interests", instructions)
        self.assertIn("recent_positive_events", instructions)
        self.assertIn("用户明确表达", instructions)
        self.assertEqual(memory["memory_meta"]["summary_batches"]["clipboard"], 3)
        self.assertEqual(
            memory["user_profile"]["preferences"]["preferences_1"]["description"],
            ["喜欢简洁回答"],
        )

    # 验证失败不覆盖已有记忆，也不标记批次完成。
    def test_failure_preserves_memory_and_batch_marker(self) -> None:
        """验证失败不覆盖已有记忆，也不标记批次完成。"""
        self.memory_store.save(
            {
                "user_profile": {"preferences": ["已有偏好"]},
                "work_study": {},
                "relationship_memory": {},
            }
        )
        service = MemorySummarizer(self.memory_store, MemoryClient(fail=True), lambda: {"api": {}})  # type: ignore[arg-type]

        self.assertFalse(service.summarize_batch("formal", self.entries, 3))

        memory = self.memory_store.load()
        self.assertEqual(
            memory["user_profile"]["preferences"]["preferences_1"]["description"],
            ["已有偏好"],
        )
        self.assertNotIn("formal", memory["memory_meta"]["summary_batches"])

    # 验证非法字段操作不会落盘或标记批次完成。
    def test_invalid_operation_preserves_memory_and_batch_marker(self) -> None:
        """验证非法字段操作不会落盘或标记批次完成。"""
        service = MemorySummarizer(
            self.memory_store,
            InvalidOperationClient(),  # type: ignore[arg-type]
            lambda: {"api": {}},
        )

        self.assertFalse(service.summarize_batch("informal", self.entries, 3))

        memory = self.memory_store.load()
        self.assertNotIn("informal", memory["memory_meta"]["summary_batches"])
        self.assertEqual(memory["user_profile"]["preferences"], {})


if __name__ == "__main__":
    unittest.main()
