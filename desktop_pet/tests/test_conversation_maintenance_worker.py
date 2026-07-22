from __future__ import annotations

import json
import shutil
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))
sys.modules.setdefault(
    "requests",
    types.SimpleNamespace(Timeout=RuntimeError, RequestException=RuntimeError, post=lambda *args, **kwargs: None),
)

from ai.memory_summarizer import MemorySummarizer  # noqa: E402
from ai.summarizer import Summarizer  # noqa: E402
from app.conversation_maintenance_worker import (  # noqa: E402
    ConversationMaintenanceWorker,
    should_run_daily_catchup,
)
from storage.chat_store import ChatStore  # noqa: E402
from storage.memory_store import MemoryStore  # noqa: E402
from storage.json_store import load_json  # noqa: E402


class MaintenanceClient:
    # 返回摘要或完整记忆 JSON。
    def __init__(self) -> None:
        """初始化摘要与记忆批处理请求计数。"""
        self.summary_calls = 0
        self.memory_calls = 0

    def is_configured(self) -> bool:
        """返回摘要或完整记忆 JSON。"""
        return True

    def chat(self, messages: list[dict[str, str]]) -> str:
        """依据系统提示返回摘要或记忆结果。"""
        if "同一模式最近三条对话摘要" in messages[0]["content"]:
            self.memory_calls += 1
            return json.dumps(
                {
                    "operations": [
                        {
                            "action": "add",
                            "field": "user_profile.preferences",
                            "description": ["测试偏好"],
                            "reason": "测试三摘要批处理",
                        }
                    ],
                    "conclusion": {"added": 1, "updated": 0, "unchanged": 0},
                },
                ensure_ascii=False,
            )
        self.summary_calls += 1
        return json.dumps({"summary": "本次摘要", "highlights": ["高光"]}, ensure_ascii=False)


class ConversationMaintenanceWorkerTests(unittest.TestCase):
    # 准备测试存储。
    def setUp(self) -> None:
        """准备测试存储。"""
        self.temp_dir = DESKTOP_PET_ROOT / "tmp_work" / "test_conversation_maintenance" / self._testMethodName
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.store = ChatStore(self.temp_dir / "chat_history.jsonl", "formal")
        self.memory_store = MemoryStore(self.temp_dir / "memory.json")
        self.client = MaintenanceClient()
        self.summarizer = Summarizer(
            self.temp_dir / "conversation_summary_formal.json",
            self.store,
            self.client,  # type: ignore[arg-type]
            config_path=self.temp_dir / "missing_config.json",
        )
        self.memory_summarizer = MemorySummarizer(
            self.memory_store,
            self.client,  # type: ignore[arg-type]
            lambda: {"api": {}},
        )
        self.state_path = self.temp_dir / "conversation_maintenance_state.json"

    # 清理测试目录。
    def tearDown(self) -> None:
        """清理测试目录。"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    # 创建并同步运行一次工作器。
    def _run(
        self,
        source: str = "round_threshold",
        force: bool = False,
        trigger_rounds: int = 1,
    ) -> None:
        """创建并同步运行一次工作器。"""
        worker = ConversationMaintenanceWorker(
            {"formal": self.summarizer},
            self.memory_summarizer,
            self.state_path,
            trigger_rounds,
            ["formal"],
            source,
            force=force,
        )
        worker.run()

    # 验证每次摘要后清理快照，第三次摘要才触发记忆总结。
    def test_archives_clears_snapshot_and_triggers_memory_on_third_sequence(self) -> None:
        """验证每次摘要后清理快照，第三次摘要才触发记忆总结。"""
        for index in range(3):
            self.store.append_message("user", f"消息{index}")
            self._run()
            self.assertEqual(self.store.all_messages(), [])
            self.assertEqual(self.client.summary_calls, index + 1)
            self.assertEqual(self.client.memory_calls, 0 if index < 2 else 1)

        archive = self.summarizer.load_summary()
        memory = self.memory_store.load()
        self.assertEqual(len(archive["summaries"]), 3)
        self.assertEqual(memory["memory_meta"]["summary_batches"]["formal"], 3)
        self.assertEqual(
            memory["user_profile"]["preferences"]["preferences_1"]["description"],
            ["测试偏好"],
        )

    # 验证快照清理后的新增消息重新从零累计摘要阈值。
    def test_summary_threshold_uses_only_messages_remaining_after_snapshot_cleanup(self) -> None:
        """验证快照清理后的新增消息重新从零累计摘要阈值。"""
        self.store.append_message("user", "第一条")
        self.store.append_message("user", "第二条")

        self._run(trigger_rounds=3)

        self.assertEqual(self.client.summary_calls, 0)
        self.assertEqual([item["content"] for item in self.store.all_messages()], ["第一条", "第二条"])

        self.store.append_message("user", "第三条")
        self._run(trigger_rounds=3)

        self.assertEqual(self.client.summary_calls, 1)
        self.assertEqual(self.store.all_messages(), [])

        self.store.append_message("user", "摘要后的新消息")
        self._run(trigger_rounds=3)

        self.assertEqual(self.client.summary_calls, 1)
        self.assertEqual([item["content"] for item in self.store.all_messages()], ["摘要后的新消息"])

    # 验证每日任务没有可总结记录时不写入完成日期。
    def test_daily_without_history_does_not_write_completion_state(self) -> None:
        """验证每日任务没有可总结记录时不写入完成日期。"""
        self._run(source="daily", force=True)

        self.assertFalse(self.state_path.exists())

    # 验证每日任务实际完成摘要后才写入完成日期。
    def test_daily_with_history_writes_completion_state(self) -> None:
        """验证每日任务实际完成摘要后才写入完成日期。"""
        self.store.append_message("user", "待每日总结")
        self._run(source="daily", force=True)

        state = load_json(self.state_path, {})
        self.assertTrue(state["last_daily_summary_date"])

    # 验证错过凌晨一点后仅在存在待处理历史时启动补跑。
    def test_daily_catchup_requires_history_after_one_am(self) -> None:
        """验证错过凌晨一点后仅在存在待处理历史时启动补跑。"""
        now = datetime(2026, 7, 11, 9, 30)
        self.assertTrue(should_run_daily_catchup(now, "2026-07-10", True))
        self.assertFalse(should_run_daily_catchup(now, "2026-07-11", True))
        self.assertFalse(should_run_daily_catchup(now, "2026-07-10", False))
        self.assertFalse(should_run_daily_catchup(datetime(2026, 7, 11, 0, 30), "2026-07-10", True))

    # 验证摘要期间的新增记录不会被快照清理删除。
    def test_snapshot_cleanup_keeps_new_message(self) -> None:
        """验证摘要期间的新增记录不会被快照清理删除。"""
        self.store.append_message("user", "第一条")
        snapshot = self.store.all_messages()
        self.store.append_message("user", "第二条")

        self.assertEqual(self.store.remove_snapshot(snapshot), 1)
        self.assertEqual([item["content"] for item in self.store.all_messages()], ["第二条"])

    # 验证剪贴板模式同样按照摘要轮数进入维护链路。
    def test_clipboard_mode_participates_in_summary_maintenance(self) -> None:
        """验证剪贴板模式同样按照摘要轮数进入维护链路。"""
        clipboard_store = ChatStore(self.temp_dir / "clipboard_history.jsonl", "clipboard")
        clipboard_summarizer = Summarizer(
            self.temp_dir / "conversation_summary_clipboard.json",
            clipboard_store,
            self.client,  # type: ignore[arg-type]
            config_path=self.temp_dir / "missing_config.json",
        )
        clipboard_store.append_message("user", "剪贴板原文")
        worker = ConversationMaintenanceWorker(
            {"clipboard": clipboard_summarizer},
            self.memory_summarizer,
            self.state_path,
            1,
            ["clipboard"],
            "round_threshold",
        )

        worker.run()

        self.assertEqual(clipboard_store.all_messages(), [])
        self.assertEqual(len(clipboard_summarizer.load_summary()["summaries"]), 1)


if __name__ == "__main__":
    unittest.main()
