from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from ai.summarizer import Summarizer  # noqa: E402


class FakeChatStore:
    def __init__(self, messages: list[dict[str, str]]) -> None:
        self._messages = messages

    def all_messages(self) -> list[dict[str, str]]:
        return list(self._messages)


class FakeMemoryStore:
    def __init__(self) -> None:
        self.merged: list[dict[str, object]] = []

    def merge(self, payload: dict[str, object]) -> None:
        self.merged.append(payload)


class EmptyMemoryDeepSeekClient:
    def __init__(self) -> None:
        self.calls = 0

    def is_configured(self) -> bool:
        return True

    def chat(self, messages: list[dict[str, str]]) -> str:
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
        self.added_texts: list[str] = []

    def add_memory_text(
        self,
        user_id: str,
        text: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.added_texts.append(text)


class SummarizerMemoryUpdateTests(unittest.TestCase):
    def test_empty_model_memory_updates_fall_back_to_local_extraction_and_mem0_write(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
