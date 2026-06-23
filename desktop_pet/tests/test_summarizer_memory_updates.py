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

from ai.summarizer import Summarizer  # noqa: E402


class FakeChatStore:
    def __init__(self, messages: list[dict[str, str]]) -> None:
        """初始化当前对象及其依赖。"""
        self._messages = messages

    def all_messages(self) -> list[dict[str, str]]:
        """处理 `all_messages` 对应的业务逻辑。"""
        return list(self._messages)


class FakeMemoryStore:
    def __init__(self) -> None:
        """初始化当前对象及其依赖。"""
        self.merged: list[dict[str, object]] = []

    def merge(self, payload: dict[str, object]) -> None:
        """处理 `merge` 对应的业务逻辑。"""
        self.merged.append(payload)


class EmptyMemoryDeepSeekClient:
    def __init__(self) -> None:
        """初始化当前对象及其依赖。"""
        self.calls = 0

    def is_configured(self) -> bool:
        """判断 `is_configured` 对应的条件是否成立。"""
        return True

    def chat(self, messages: list[dict[str, str]]) -> str:
        """处理 `chat` 对应的业务逻辑。"""
        self.calls += 1
        if self.calls == 1:
            return json.dumps({"summary": "用户提到了偏好和项目。", "highlights": []}, ensure_ascii=False)
        return json.dumps(
            {
                "user_profile": {
                    "preferences": [],
                    "communication_style": [],
                    "important_personal_notes": [],
                },
                "work_study": {
                    "current_learning_topics": [],
                    "current_projects": [],
                    "useful_context": [],
                },
            },
            ensure_ascii=False,
        )


class FakeMem0MemoryService:
    def __init__(self) -> None:
        """初始化当前对象及其依赖。"""
        self.added_texts: list[str] = []

    def add_memory_text(
        self,
        user_id: str,
        text: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        """添加 `add_memory_text` 对应的内容。"""
        self.added_texts.append(text)


class SummarizerMemoryUpdateTests(unittest.TestCase):
    def test_empty_model_memory_updates_fall_back_to_local_extraction_and_mem0_write(self) -> None:
        """验证 `test_empty_model_memory_updates_fall_back_to_local_extraction_and_mem0_write` 对应的行为。"""
        temp_dir = DESKTOP_PET_ROOT / "tmp_work" / "test_summarizer_memory_updates"
        temp_dir.mkdir(parents=True, exist_ok=True)
        summary_path = temp_dir / "conversation_summary_informal.json"
        summary_path.write_text(
            json.dumps(
                {
                    "summary": "",
                    "covered_message_count": 0,
                    "highlights": [],
                    "last_updated": "",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        memory_store = FakeMemoryStore()
        mem0_service = FakeMem0MemoryService()
        summarizer = Summarizer(
            summary_path,
            FakeChatStore(
                [
                    {"role": "user", "content": "我喜欢Python项目，最近在实现桌宠代码。"},
                    {"role": "assistant", "content": "收到。"},
                ]
            ),  # type: ignore[arg-type]
            memory_store,  # type: ignore[arg-type]
            EmptyMemoryDeepSeekClient(),  # type: ignore[arg-type]
            mem0_memory_service=mem0_service,
        )

        summarizer.maybe_summarize(trigger_rounds=1, force=True)

        self.assertTrue(memory_store.merged)
        merged_text = json.dumps(memory_store.merged[-1], ensure_ascii=False)
        self.assertIn("我喜欢Python项目", merged_text)
        self.assertTrue(mem0_service.added_texts)

    def test_formal_question_with_empty_model_memory_updates_falls_back_to_learning_topic(
        self,
    ) -> None:
        """验证 `test_formal_question_with_empty_model_memory_updates_falls_back_to_learning_topic` 对应的行为。"""
        temp_dir = DESKTOP_PET_ROOT / "tmp_work" / "test_formal_summarizer_memory_updates"
        temp_dir.mkdir(parents=True, exist_ok=True)
        summary_path = temp_dir / "conversation_summary_formal.json"
        summary_path.write_text(
            json.dumps(
                {
                    "summary": "",
                    "covered_message_count": 0,
                    "highlights": [],
                    "last_updated": "",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        memory_store = FakeMemoryStore()
        summarizer = Summarizer(
            summary_path,
            FakeChatStore(
                [
                    {"role": "user", "content": "conda环境和Python虚拟环境的区别是什么？"},
                    {"role": "assistant", "content": "两者的管理范围和包来源不同。"},
                ]
            ),  # type: ignore[arg-type]
            memory_store,  # type: ignore[arg-type]
            EmptyMemoryDeepSeekClient(),  # type: ignore[arg-type]
        )

        summarizer.maybe_summarize(trigger_rounds=1, force=True)

        self.assertTrue(memory_store.merged)
        merged_text = json.dumps(memory_store.merged[-1], ensure_ascii=False)
        self.assertIn("conda环境和Python虚拟环境", merged_text)

    def test_question_keywords_fall_back_to_learning_topics(self) -> None:
        """验证 `test_question_keywords_fall_back_to_learning_topics` 对应的行为。"""
        temp_dir = DESKTOP_PET_ROOT / "tmp_work" / "test_question_keyword_memory_updates"
        temp_dir.mkdir(parents=True, exist_ok=True)
        summary_path = temp_dir / "conversation_summary_informal.json"
        summary_path.write_text(
            json.dumps(
                {
                    "summary": "",
                    "covered_message_count": 0,
                    "highlights": [],
                    "last_updated": "",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        memory_store = FakeMemoryStore()
        summarizer = Summarizer(
            summary_path,
            FakeChatStore(
                [
                    {"role": "user", "content": "请问PySide6透明窗口怎么做？"},
                    {"role": "assistant", "content": "可以使用透明背景和无边框窗口。"},
                    {"role": "user", "content": "如何实现桌宠启动时自动问候？"},
                    {"role": "assistant", "content": "可以用 QTimer 延迟触发。"},
                ]
            ),  # type: ignore[arg-type]
            memory_store,  # type: ignore[arg-type]
            EmptyMemoryDeepSeekClient(),  # type: ignore[arg-type]
        )

        summarizer.maybe_summarize(trigger_rounds=1, force=True)

        self.assertTrue(memory_store.merged)
        topics = memory_store.merged[-1]["work_study"]["current_learning_topics"]  # type: ignore[index]
        self.assertIn("请问PySide6透明窗口怎么做？", topics)
        self.assertIn("如何实现桌宠启动时自动问候？", topics)

    def test_informal_summary_mode_does_not_use_formal_question_fallback(self) -> None:
        """验证 `test_informal_summary_mode_does_not_use_formal_question_fallback` 对应的行为。"""
        temp_dir = DESKTOP_PET_ROOT / "tmp_work" / "test_informal_summary_mode"
        temp_dir.mkdir(parents=True, exist_ok=True)
        summary_path = temp_dir / "conversation_summary_informal.json"
        summary_path.write_text(
            json.dumps(
                {
                    "summary": "",
                    "covered_message_count": 0,
                    "highlights": [],
                    "last_updated": "",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        memory_store = FakeMemoryStore()
        summarizer = Summarizer(
            summary_path,
            FakeChatStore(
                [
                    {"role": "user", "content": "我今天有点累。"},
                    {"role": "assistant", "content": "辛苦了。"},
                ]
            ),  # type: ignore[arg-type]
            memory_store,  # type: ignore[arg-type]
            EmptyMemoryDeepSeekClient(),  # type: ignore[arg-type]
        )

        summarizer.maybe_summarize(trigger_rounds=1, force=True)

        self.assertTrue(memory_store.merged)
        topics = memory_store.merged[-1]["work_study"]["current_learning_topics"]  # type: ignore[index]
        self.assertEqual([], topics)

    def test_user_interaction_preference_writes_relationship_memory(self) -> None:
        """验证 `test_user_interaction_preference_writes_relationship_memory` 对应的行为。"""
        temp_dir = DESKTOP_PET_ROOT / "tmp_work" / "test_relationship_memory_updates"
        temp_dir.mkdir(parents=True, exist_ok=True)
        summary_path = temp_dir / "conversation_summary_informal.json"
        summary_path.write_text(
            json.dumps(
                {
                    "summary": "",
                    "covered_message_count": 0,
                    "highlights": [],
                    "last_updated": "",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        memory_store = FakeMemoryStore()
        summarizer = Summarizer(
            summary_path,
            FakeChatStore(
                [
                    {
                        "role": "user",
                        "content": "以后不要总是问我确认，直接给我可执行方案。",
                    },
                    {"role": "assistant", "content": "好。"},
                ]
            ),  # type: ignore[arg-type]
            memory_store,  # type: ignore[arg-type]
            EmptyMemoryDeepSeekClient(),  # type: ignore[arg-type]
        )

        summarizer.maybe_summarize(trigger_rounds=1, force=True)

        self.assertTrue(memory_store.merged)
        communication_style = memory_store.merged[-1]["relationship_memory"][
            "communication_style"
        ]  # type: ignore[index]
        self.assertEqual(
            communication_style["confirmation_preference"],
            "avoid_unnecessary_confirmation",
        )
        self.assertEqual(
            communication_style["preferred_response_style"],
            "direct_actionable",
        )

    def test_assistant_claim_does_not_write_relationship_memory(self) -> None:
        """验证 `test_assistant_claim_does_not_write_relationship_memory` 对应的行为。"""
        temp_dir = DESKTOP_PET_ROOT / "tmp_work" / "test_no_assistant_relationship_memory"
        temp_dir.mkdir(parents=True, exist_ok=True)
        summary_path = temp_dir / "conversation_summary_informal.json"
        summary_path.write_text(
            json.dumps(
                {
                    "summary": "",
                    "covered_message_count": 0,
                    "highlights": [],
                    "last_updated": "",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        memory_store = FakeMemoryStore()
        summarizer = Summarizer(
            summary_path,
            FakeChatStore(
                [
                    {"role": "user", "content": "这个功能怎么做？"},
                    {"role": "assistant", "content": "你喜欢直接详细的回答，我之后都会这样。"},
                ]
            ),  # type: ignore[arg-type]
            memory_store,  # type: ignore[arg-type]
            EmptyMemoryDeepSeekClient(),  # type: ignore[arg-type]
        )

        summarizer.maybe_summarize(trigger_rounds=1, force=True)

        self.assertTrue(memory_store.merged)
        relationship_memory = memory_store.merged[-1].get("relationship_memory", {})
        relationship_text = json.dumps(relationship_memory, ensure_ascii=False)
        self.assertNotIn("direct_actionable", relationship_text)
        self.assertNotIn("high", relationship_text)


if __name__ == "__main__":
    unittest.main()
