from __future__ import annotations

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
from storage.json_store import load_json  # noqa: E402


class ChatStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        """准备当前测试所需的环境和数据。"""
        self.temp_dir = DESKTOP_PET_ROOT / "tmp_work" / "test_chat_store" / self._testMethodName
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.temp_dir / "chat_history.json"

    def tearDown(self) -> None:
        """清理当前测试产生的环境和数据。"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_clear_history_with_timestamp_writes_single_empty_payload(self) -> None:
        """清空聊天记录时同一次写入保留清理时间。"""
        store = ChatStore(self.path)
        store.append_message("user", "你好")

        store.clear_history_with_timestamp("2026-06-24T21:00:00")

        payload = load_json(self.path, {})
        self.assertEqual(payload["messages"], [])
        self.assertEqual(payload["last_cleaned_at"], "2026-06-24T21:00:00")

    def test_multiple_store_instances_append_without_lost_updates(self) -> None:
        """同一路径的多个存储实例并发追加时共享锁，不丢失消息。"""
        stores = [ChatStore(self.path), ChatStore(self.path)]

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


if __name__ == "__main__":
    unittest.main()
