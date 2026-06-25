from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))
sys.modules.setdefault(
    "requests",
    types.SimpleNamespace(
        Timeout=RuntimeError,
        RequestException=RuntimeError,
        post=lambda *args, **kwargs: None,
    ),
)

from ai.context_manager import ContextManager  # noqa: E402
from ai.summarizer import Summarizer  # noqa: E402
from storage.chat_store import ChatStore  # noqa: E402
from storage.json_store import save_json  # noqa: E402


class FakeMemoryStore:
    # 为 FakeMemoryStore 测试替身提供merge行为。
    def merge(self, payload: dict[str, object]) -> None:
        """为 FakeMemoryStore 测试替身提供merge行为。"""
        self.payload = payload


class BudgetRecordingClient:
    # 初始化当前对象及其依赖。
    def __init__(self) -> None:
        """初始化当前对象及其依赖。"""
        self.messages: list[list[dict[str, str]]] = []
        self.calls = 0

    # 为测试准备isconfigured数据或断言辅助结果。
    def is_configured(self) -> bool:
        """为测试准备isconfigured数据或断言辅助结果。"""
        return True

    # 为测试准备聊天数据或断言辅助结果。
    def chat(self, messages: list[dict[str, str]]) -> str:
        """为测试准备聊天数据或断言辅助结果。"""
        self.calls += 1
        self.messages.append(messages)
        if self.calls == 1:
            return json.dumps({"summary": "summary", "highlights": ["highlight"]}, ensure_ascii=False)
        return json.dumps(
            {
                "user_profile": {"preferences": [], "communication_style": [], "important_personal_notes": []},
                "work_study": {"current_learning_topics": [], "current_projects": [], "useful_context": []},
                "relationship_memory": {},
            },
            ensure_ascii=False,
        )


class ContextBudgetControlsTests(unittest.TestCase):
    # 准备当前测试所需的环境和数据。
    def setUp(self) -> None:
        """准备当前测试所需的环境和数据。"""
        self.temp_dir = DESKTOP_PET_ROOT / "tmp_work" / self._testMethodName
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.temp_dir / "app_config.json"
        self.summary_path = self.temp_dir / "conversation_summary_informal.json"
        save_json(
            self.summary_path,
            {
                "summary": "",
                "covered_message_count": 0,
                "highlights": [],
                "last_updated": "",
            },
        )

    # 验证上下文 manager limits 消息 count and 消息 chars场景下的预期结果。
    def test_context_manager_limits_message_count_and_message_chars(self) -> None:
        """验证上下文 manager limits 消息 count and 消息 chars场景下的预期结果。"""
        save_json(
            self.config_path,
            {
                "api": {
                    "max_history_messages": 3,
                    "max_history_message_chars": 40,
                }
            },
        )
        chat_store = ChatStore(self.temp_dir / "chat_history.json")
        for index in range(6):
            chat_store.append_message("user", f"msg-{index}-" + ("X" * 80))

        manager = ContextManager(self.config_path, chat_store, chat_store)
        recent = manager.recent_messages()

        self.assertEqual(3, len(recent))
        self.assertTrue(all(len(item["content"]) <= 40 for item in recent))

    # 验证上下文 manager uses defaults when 预算 keys missing场景下的预期结果。
    def test_context_manager_uses_defaults_when_budget_keys_missing(self) -> None:
        """验证上下文 manager uses defaults when 预算 keys missing场景下的预期结果。"""
        save_json(self.config_path, {"api": {}})
        chat_store = ChatStore(self.temp_dir / "chat_history_defaults.json")
        for index in range(15):
            chat_store.append_message("user", f"msg-{index}")

        manager = ContextManager(self.config_path, chat_store, chat_store)
        recent = manager.recent_messages()

        self.assertEqual(12, len(recent))

    # 验证摘要 输入 respects 预算场景下的预期结果。
    def test_summary_input_respects_budget(self) -> None:
        """验证摘要 输入 respects 预算场景下的预期结果。"""
        save_json(
            self.config_path,
            {
                "api": {
                    "summary_max_input_chars": 220,
                    "memory_extract_max_input_chars": 180,
                    "max_history_message_chars": 120,
                    "max_summary_chars": 100,
                }
            },
        )
        chat_store = ChatStore(self.temp_dir / "chat_history_summary.json")
        for index in range(12):
            chat_store.append_message("user", f"user-{index}-" + ("U" * 120))
            chat_store.append_message("assistant", f"assistant-{index}-" + ("A" * 120))

        client = BudgetRecordingClient()
        summarizer = Summarizer(
            self.summary_path,
            chat_store,
            FakeMemoryStore(),  # type: ignore[arg-type]
            client,  # type: ignore[arg-type]
            config_path=self.config_path,
        )

        summarizer.maybe_summarize(trigger_rounds=1, force=True)

        self.assertGreaterEqual(len(client.messages), 2)
        summary_prompt = client.messages[0][-1]["content"]
        memory_prompt = client.messages[1][-1]["content"]
        self.assertLessEqual(len(summary_prompt), 220)
        self.assertLessEqual(len(memory_prompt), 180)


if __name__ == "__main__":
    unittest.main()
