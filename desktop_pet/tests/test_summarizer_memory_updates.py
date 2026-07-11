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
    # 初始化当前对象及其依赖。
    def __init__(self, messages: list[dict[str, str]]) -> None:
        """初始化当前对象及其依赖。"""
        self._messages = messages

    # 为 FakeChatStore 测试替身提供all消息行为。
    def all_messages(self) -> list[dict[str, str]]:
        """为 FakeChatStore 测试替身提供all消息行为。"""
        return list(self._messages)


class FakeMemoryStore:
    # 初始化当前对象及其依赖。
    def __init__(self) -> None:
        """初始化当前对象及其依赖。"""
        self.merged: list[dict[str, object]] = []

    # 为 FakeMemoryStore 测试替身提供merge行为。
    def merge(self, payload: dict[str, object]) -> None:
        """为 FakeMemoryStore 测试替身提供merge行为。"""
        self.merged.append(payload)


class EmptyMemoryDeepSeekClient:
    # 初始化当前对象及其依赖。
    def __init__(self) -> None:
        """初始化当前对象及其依赖。"""
        self.calls = 0

    # 为测试准备isconfigured数据或断言辅助结果。
    def is_configured(self) -> bool:
        """为测试准备isconfigured数据或断言辅助结果。"""
        return True

    # 为测试准备聊天数据或断言辅助结果。
    def chat(self, messages: list[dict[str, str]]) -> str:
        """为测试准备聊天数据或断言辅助结果。"""
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
    # 初始化当前对象及其依赖。
    def __init__(self) -> None:
        """初始化当前对象及其依赖。"""
        self.added_texts: list[str] = []

    # 为 FakeMem0MemoryService 测试替身提供add 记忆 文本行为。
    def add_memory_text(
        self,
        user_id: str,
        text: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        """为 FakeMem0MemoryService 测试替身提供add 记忆 文本行为。"""
        self.added_texts.append(text)


class SummarizerMemoryUpdateTests(unittest.TestCase):
    # 验证单次对话摘要不再直接写入记忆或 Mem0。
    def test_single_summary_does_not_write_memory_or_mem0(self) -> None:
        """验证单次对话摘要不再直接写入记忆或 Mem0。"""
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

        self.assertEqual(memory_store.merged, [])
        self.assertEqual(mem0_service.added_texts, [])

    # 验证正式问答单次摘要不再触发记忆更新。
    def test_formal_single_summary_does_not_update_memory(
        self,
    ) -> None:
        """验证正式问答摘要缺少记忆更新时会回退为学习主题。"""
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

        self.assertEqual(memory_store.merged, [])

    # 验证关键词不会绕过批次机制直接写入记忆。
    def test_question_keywords_do_not_bypass_memory_batch(self) -> None:
        """验证关键词不会绕过批次机制直接写入记忆。"""
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

        self.assertEqual(memory_store.merged, [])

    # 验证非正式单次摘要不再直接更新记忆。
    def test_informal_single_summary_does_not_update_memory(self) -> None:
        """验证非正式单次摘要不再直接更新记忆。"""
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

        self.assertEqual(memory_store.merged, [])

    # 验证互动偏好不会绕过三摘要批次直接写入关系记忆。
    def test_interaction_preference_does_not_bypass_memory_batch(self) -> None:
        """验证互动偏好不会绕过三摘要批次直接写入关系记忆。"""
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

        self.assertEqual(memory_store.merged, [])

    # 验证助手内容不会绕过批次机制直接写入关系记忆。
    def test_assistant_content_does_not_bypass_memory_batch(self) -> None:
        """验证助手内容不会绕过批次机制直接写入关系记忆。"""
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

        self.assertEqual(memory_store.merged, [])


if __name__ == "__main__":
    unittest.main()
