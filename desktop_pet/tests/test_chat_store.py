from __future__ import annotations

import json
import logging
import shutil
import sys
import threading
import types
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

logger_module = types.ModuleType("utils.logger")
logger_module.get_logger = logging.getLogger
sys.modules.setdefault("utils.logger", logger_module)

from storage.chat_store import ChatStore  # noqa: E402


class ChatStoreTests(unittest.TestCase):
    # 准备当前测试所需的环境和数据。
    def setUp(self) -> None:
        """准备当前测试所需的环境和数据。"""
        self.temp_dir = DESKTOP_PET_ROOT / "tmp_work" / "test_chat_store" / self._testMethodName
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.temp_dir / "chat_history.jsonl"

    # 清理当前测试产生的环境和数据。
    def tearDown(self) -> None:
        """清理当前测试产生的环境和数据。"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    # 验证共享 JSONL 为每条消息写入模式字段并按模式隔离读取。
    def test_append_and_read_are_isolated_by_mode(self) -> None:
        """验证共享 JSONL 为每条消息写入模式字段并按模式隔离读取。"""
        formal = ChatStore(self.path, "formal")
        informal = ChatStore(self.path, "informal")
        formal.append_message("user", "正式问题")
        informal.append_message("user", "普通聊天")
        formal.append_message("assistant", "正式回答")

        records = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual([item["mode"] for item in records], ["formal", "informal", "formal"])
        self.assertTrue(all(item["id"] for item in records))
        self.assertTrue(all("+00:00" in item["timestamp"] for item in records))
        self.assertEqual([item["content"] for item in formal.all_messages()], ["正式问题", "正式回答"])
        self.assertEqual([item["content"] for item in informal.all_messages()], ["普通聊天"])
        self.assertTrue(formal.should_trigger_summary(1, 0))
        self.assertTrue(informal.should_trigger_summary(1, 0))

    # 验证提醒、剪贴板和截图预留模式合法且不混入普通聊天模式。
    def test_extended_modes_are_valid_and_isolated(self) -> None:
        """验证提醒、剪贴板和截图预留模式合法且隔离。"""
        stores = {
            mode: ChatStore(self.path, mode)
            for mode in ("formal", "informal", "remind", "clipboard", "screenshot")
        }
        for mode, store in stores.items():
            store.append_message("user", f"{mode}-content")

        for mode, store in stores.items():
            self.assertEqual([item["content"] for item in store.all_messages()], [f"{mode}-content"])

    # 验证会话重标仅影响具有相同内部标识的当前模式记录。
    def test_reassign_conversation_changes_only_matching_records(self) -> None:
        """验证会话重标仅影响具有相同内部标识的当前模式记录。"""
        informal = ChatStore(self.path, "informal")
        remind = ChatStore(self.path, "remind")
        informal.append_message("user", "提醒我休息", {"conversation_id": "reminder-turn"})
        informal.append_message("assistant", "好的", {"conversation_id": "reminder-turn"})
        informal.append_message("user", "普通聊天", {"conversation_id": "normal-turn"})

        changed = informal.reassign_conversation("reminder-turn", "remind")

        self.assertEqual(changed, 2)
        self.assertEqual([item["content"] for item in informal.all_messages()], ["普通聊天"])
        self.assertEqual([item["content"] for item in remind.all_messages()], ["提醒我休息", "好的"])

    # 清理一个模式时仅移除其 JSONL 行，另一模式记录保持不变。
    def test_clear_history_keeps_other_mode_records(self) -> None:
        """清理一个模式时仅移除其 JSONL 行，另一模式记录保持不变。"""
        formal = ChatStore(self.path, "formal")
        informal = ChatStore(self.path, "informal")
        formal.append_message("user", "正式问题")
        informal.append_message("user", "普通聊天")

        formal.clear_history_with_timestamp("2026-06-24T21:00:00")

        self.assertEqual(formal.all_messages(), [])
        self.assertEqual([item["content"] for item in informal.all_messages()], ["普通聊天"])

    # 验证快照清理不会删除摘要运行期间新追加的同模式记录。
    def test_remove_snapshot_keeps_messages_appended_after_snapshot(self) -> None:
        """验证快照清理不会删除摘要运行期间新追加的同模式记录。"""
        formal = ChatStore(self.path, "formal")
        formal.append_message("user", "待总结")
        snapshot = formal.all_messages()
        formal.append_message("user", "摘要期间新增")

        removed = formal.remove_snapshot(snapshot)

        self.assertEqual(removed, 1)
        self.assertEqual([item["content"] for item in formal.all_messages()], ["摘要期间新增"])

    # 同一路径的多个存储实例并发追加时共享锁，不丢失消息。
    def test_multiple_store_instances_append_without_lost_updates(self) -> None:
        """同一路径的多个存储实例并发追加时共享锁，不丢失消息。"""
        stores = [ChatStore(self.path, "informal"), ChatStore(self.path, "informal")]

        # 追加一组可唯一识别的测试消息。
        def append_messages(store_index: int) -> None:
            """追加一组可唯一识别的测试消息。"""
            store = stores[store_index]
            for index in range(25):
                store.append_message("user", f"{store_index}-{index}")

        threads = [
            threading.Thread(target=append_messages, args=(store_index,))
            for store_index in range(len(stores))
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        messages = stores[0].all_messages()
        contents = {message["content"] for message in messages}
        self.assertEqual(len(messages), 50)
        self.assertEqual(len(contents), 50)

    # 验证损坏的单条 JSONL 不会影响其他模式记录读取。
    def test_malformed_jsonl_line_is_skipped(self) -> None:
        """验证损坏的单条 JSONL 不会影响其他模式记录读取。"""
        self.path.write_text(
            "\n".join(
                [
                    json.dumps({"role": "user", "content": "正式", "timestamp": "2026-01-01T00:00:00+00:00", "metadata": {}, "mode": "formal"}, ensure_ascii=False),
                    "{broken",
                    json.dumps({"role": "user", "content": "普通", "timestamp": "2026-01-01T00:00:01+00:00", "metadata": {}, "mode": "informal"}, ensure_ascii=False),
                ]
            ) + "\n",
            encoding="utf-8",
        )

        self.assertEqual([item["content"] for item in ChatStore(self.path, "formal").all_messages()], ["正式"])
        self.assertEqual([item["content"] for item in ChatStore(self.path, "informal").all_messages()], ["普通"])

    # 验证首次迁移旧历史，补齐模式字段并在已有 JSONL 时避免重复迁移。
    def test_migrate_legacy_histories_once_in_timestamp_order(self) -> None:
        """验证首次迁移旧历史，补齐模式字段并避免重复迁移。"""
        formal_path = self.temp_dir / "chat_history_formal.json"
        informal_path = self.temp_dir / "chat_history_informal.json"
        formal_path.write_text(
            json.dumps({"messages": [{"role": "user", "content": "正式", "timestamp": "2026-01-01T00:00:02", "metadata": {}}]}, ensure_ascii=False),
            encoding="utf-8",
        )
        informal_path.write_text(
            json.dumps({"messages": [{"role": "user", "content": "普通", "timestamp": "2026-01-01T00:00:01", "metadata": {}}]}, ensure_ascii=False),
            encoding="utf-8",
        )

        migrated = ChatStore.migrate_legacy_histories(
            self.path,
            {"formal": formal_path, "informal": informal_path},
        )
        records = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]

        self.assertTrue(migrated)
        self.assertEqual([item["content"] for item in records], ["普通", "正式"])
        self.assertEqual([item["mode"] for item in records], ["informal", "formal"])
        self.assertTrue(formal_path.exists())
        self.assertFalse(ChatStore.migrate_legacy_histories(self.path, {"formal": formal_path, "informal": informal_path}))
        self.assertEqual(len(self.path.read_text(encoding="utf-8").splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
