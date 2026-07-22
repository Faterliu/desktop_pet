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
    types.SimpleNamespace(
        Timeout=RuntimeError,
        RequestException=RuntimeError,
        post=lambda *args, **kwargs: None,
    ),
)

from ai.context_manager import ContextManager  # noqa: E402
from ai.prompt_builder import PromptBuilder  # noqa: E402
from ai.summarizer import Summarizer  # noqa: E402
from storage.chat_store import ChatStore  # noqa: E402
from storage.json_store import load_json, save_json  # noqa: E402


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
        return json.dumps({"summary": "summary", "highlights": ["highlight"]}, ensure_ascii=False)


class ContextBudgetControlsTests(unittest.TestCase):
    # 准备当前测试所需的环境和数据。
    def setUp(self) -> None:
        """准备当前测试所需的环境和数据。"""
        self.temp_dir = DESKTOP_PET_ROOT / "tmp_work" / self._testMethodName
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.temp_dir / "app_config.json"
        self.summary_path = self.temp_dir / "conversation_summary_informal.json"
        save_json(
            self.summary_path,
            {"summaries": []},
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
        chat_store = ChatStore(self.temp_dir / "chat_history.jsonl")
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
        chat_store = ChatStore(self.temp_dir / "chat_history_defaults.jsonl")
        for index in range(15):
            chat_store.append_message("user", f"msg-{index}")

        manager = ContextManager(self.config_path, chat_store, chat_store)
        recent = manager.recent_messages()

        self.assertEqual(12, len(recent))

    # 验证共享 JSONL 下正式和非正式模式读取到的上下文彼此隔离。
    def test_context_manager_filters_shared_jsonl_by_mode(self) -> None:
        """验证共享 JSONL 下正式和非正式模式读取到的上下文彼此隔离。"""
        save_json(self.config_path, {"api": {"max_history_messages": 8}})
        path = self.temp_dir / "chat_history_modes.jsonl"
        formal_store = ChatStore(path, "formal")
        informal_store = ChatStore(path, "informal")
        formal_store.append_message("user", "正式问题")
        informal_store.append_message("user", "普通聊天")
        manager = ContextManager(self.config_path, formal_store, informal_store)

        formal_messages = manager.recent_messages(formal_qa_mode=True)
        informal_messages = manager.recent_messages(formal_qa_mode=False)

        self.assertEqual([item["content"] for item in formal_messages], ["正式问题"])
        self.assertEqual([item["content"] for item in informal_messages], ["普通聊天"])

    # 验证两份摘要从共享 JSONL 中各自归档对应模式。
    def test_summarizers_use_separate_modes_from_shared_jsonl(self) -> None:
        """验证两份摘要从共享 JSONL 中各自总结对应模式。"""
        save_json(self.config_path, {"api": {"summary_max_input_chars": 600}})
        formal_summary_path = self.temp_dir / "conversation_summary_formal.json"
        informal_summary_path = self.temp_dir / "conversation_summary_informal.json"
        for summary_path in (formal_summary_path, informal_summary_path):
            save_json(summary_path, {"summaries": []})

        path = self.temp_dir / "chat_history_summary_modes.jsonl"
        formal_store = ChatStore(path, "formal")
        informal_store = ChatStore(path, "informal")
        formal_store.append_message("user", "如何部署这个项目？")
        informal_store.append_message("user", "今天有点累。")
        formal_client = BudgetRecordingClient()
        informal_client = BudgetRecordingClient()
        formal_summarizer = Summarizer(
            formal_summary_path,
            formal_store,
            formal_client,
            config_path=self.config_path,
        )
        informal_summarizer = Summarizer(
            informal_summary_path,
            informal_store,
            informal_client,
            config_path=self.config_path,
        )

        formal_summarizer.maybe_summarize(trigger_rounds=1, force=True)
        informal_summarizer.maybe_summarize(trigger_rounds=1, force=True)

        formal_prompt = formal_client.messages[0][-1]["content"]
        informal_prompt = informal_client.messages[0][-1]["content"]
        self.assertIn("如何部署这个项目？", formal_prompt)
        self.assertNotIn("今天有点累。", formal_prompt)
        self.assertIn("今天有点累。", informal_prompt)
        self.assertNotIn("如何部署这个项目？", informal_prompt)
        self.assertNotIn("summary", load_json(formal_summary_path, {}))
        self.assertNotIn("summary", load_json(informal_summary_path, {}))
        self.assertEqual(len(load_json(informal_summary_path, {})["summaries"]), 1)

    # 验证摘要 输入 respects 预算场景下的预期结果。
    def test_summary_input_respects_budget(self) -> None:
        """验证摘要 输入 respects 预算场景下的预期结果。"""
        save_json(
            self.config_path,
            {
                "api": {
                    "summary_max_input_chars": 220,
                    "max_history_message_chars": 120,
                    "max_summary_chars": 100,
                }
            },
        )
        chat_store = ChatStore(self.temp_dir / "chat_history_summary.jsonl")
        for index in range(12):
            chat_store.append_message("user", f"user-{index}-" + ("U" * 120))
            chat_store.append_message("assistant", f"assistant-{index}-" + ("A" * 120))

        client = BudgetRecordingClient()
        summarizer = Summarizer(
            self.summary_path,
            chat_store,
            client,  # type: ignore[arg-type]
            config_path=self.config_path,
        )

        summarizer.maybe_summarize(trigger_rounds=1, force=True)

        self.assertEqual(len(client.messages), 1)
        summary_prompt = client.messages[0][-1]["content"]
        self.assertLessEqual(len(summary_prompt), 220)

    # 验证旧版单摘要会保留为第一条归档，之后摘要按序号追加。
    def test_legacy_summary_migrates_and_appends_without_overwrite(self) -> None:
        """验证旧版单摘要会保留为第一条归档，之后摘要按序号追加。"""
        save_json(
            self.summary_path,
            {"summary": "旧摘要", "covered_message_count": 24, "highlights": ["旧高光"], "last_updated": "2026-01-01T00:00:00+00:00"},
        )
        store = ChatStore(self.temp_dir / "legacy_summary_history.jsonl", "clipboard")
        store.append_message("user", "新的剪贴板内容")
        summarizer = Summarizer(
            self.summary_path,
            store,
            BudgetRecordingClient(),  # type: ignore[arg-type]
            config_path=self.config_path,
        )

        result = summarizer.maybe_summarize(trigger_rounds=1, force=True, trigger_source="daily")
        payload = load_json(self.summary_path, {})

        self.assertIsNotNone(result)
        self.assertNotIn("covered_message_count", payload)
        self.assertNotIn("summary", payload)
        self.assertNotIn("highlights", payload)
        self.assertNotIn("last_updated", payload)
        self.assertEqual([item["summary"] for item in payload["summaries"]], ["旧摘要", "summary"])
        self.assertEqual(payload["summaries"][-1]["trigger_source"], "daily")

    # 验证带有旧顶层镜像字段的归档会在读取时收敛为唯一摘要结构。
    def test_summary_archive_removes_redundant_legacy_top_level_fields(self) -> None:
        """验证带有旧顶层镜像字段的归档会在读取时收敛为唯一摘要结构。"""
        save_json(
            self.summary_path,
            {
                "summary": "过期镜像摘要",
                "highlights": ["过期高光"],
                "covered_message_count": 3,
                "last_updated": "2026-01-01T00:00:00+00:00",
                "summaries": [
                    {
                        "sequence": 1,
                        "summary": "归档摘要",
                        "highlights": ["归档高光"],
                        "created_at": "2026-01-02T00:00:00+00:00",
                        "trigger_source": "round_threshold",
                    }
                ],
            },
        )
        summarizer = Summarizer(
            self.summary_path,
            ChatStore(self.temp_dir / "archive_history.jsonl"),
            BudgetRecordingClient(),  # type: ignore[arg-type]
            config_path=self.config_path,
        )

        archive = summarizer.load_summary()

        self.assertEqual(set(archive), {"summaries"})
        self.assertEqual(archive["summaries"][0]["summary"], "归档摘要")
        self.assertEqual(load_json(self.summary_path, {}), archive)

    # 验证提示词只组合当前模式摘要归档中的内容。
    def test_prompt_summary_archive_uses_latest_entries(self) -> None:
        """验证提示词只组合当前模式摘要归档中的内容。"""
        text = PromptBuilder._format_summary_archive(
            {
                "summaries": [
                    {"sequence": 1, "summary": "较早摘要"},
                    {"sequence": 2, "summary": "最新摘要"},
                ]
            }
        )

        self.assertEqual(text, "最新摘要\n较早摘要")
        self.assertEqual(
            PromptBuilder._format_summary_archive({"summary": "不应再读取的旧摘要"}),
            "",
        )


if __name__ == "__main__":
    unittest.main()
