from __future__ import annotations

import logging
import shutil
import sys
import types
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

logger_module = types.ModuleType("utils.logger")
logger_module.get_logger = logging.getLogger
sys.modules.setdefault("utils.logger", logger_module)

from storage.json_store import (  # noqa: E402
    cleanup_tmp_json_files,
    ensure_json_file,
    load_json,
    save_json,
)


class JsonStoreTests(unittest.TestCase):
    # 准备当前测试所需的环境和数据。
    def setUp(self) -> None:
        """准备当前测试所需的环境和数据。"""
        self.temp_dir = DESKTOP_PET_ROOT / "tmp_work" / "test_json_store" / self._testMethodName
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.temp_dir / "store.json"

    # 清理当前测试产生的环境和数据。
    def tearDown(self) -> None:
        """清理当前测试产生的环境和数据。"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    # 验证load JSON creates missing 文件 from 默认值场景下的预期结果。
    def test_load_json_creates_missing_file_from_default(self) -> None:
        """验证load JSON creates missing 文件 from 默认值场景下的预期结果。"""
        default = {"items": []}

        loaded = load_json(self.path, default)
        loaded["items"].append("changed")

        self.assertEqual(load_json(self.path, {}), {"items": []})
        self.assertEqual(default, {"items": []})

    # 验证ensure JSON 文件 creates missing 文件场景下的预期结果。
    def test_ensure_json_file_creates_missing_file(self) -> None:
        """验证ensure JSON 文件 creates missing 文件场景下的预期结果。"""
        ensured = ensure_json_file(self.path, {"ready": True})

        self.assertEqual(ensured, self.path)
        self.assertEqual(load_json(self.path, {}), {"ready": True})

    # 验证保存 JSON 仅更新主文件，不生成备份文件。
    def test_save_json_writes_valid_json_without_backup(self) -> None:
        """验证保存 JSON 仅更新主文件，不生成备份文件。"""
        save_json(self.path, {"version": 1})
        save_json(self.path, {"version": 2})

        self.assertEqual(load_json(self.path, {}), {"version": 2})
        self.assertFalse(self.path.with_suffix(".json.bak").exists())

    # 主文件损坏时隔离损坏文件，并返回默认值而不读取旧备份。
    def test_load_json_returns_default_when_primary_is_corrupt(self) -> None:
        """主文件损坏时隔离损坏文件，并返回默认值。"""
        self.path.with_suffix(".json.bak").write_text('{"safe": true}', encoding="utf-8")
        self.path.write_text('{"broken": ', encoding="utf-8")

        loaded = load_json(self.path, {"safe": False})

        self.assertEqual(loaded, {"safe": False})
        self.assertFalse(self.path.exists())
        self.assertEqual(len(list(self.temp_dir.glob("store.json.corrupt.*"))), 1)

    # 主文件缺失时忽略遗留备份，并按默认值创建新的主文件。
    def test_load_json_ignores_legacy_backup_when_primary_is_missing(self) -> None:
        """主文件缺失时忽略遗留备份，并按默认值创建新的主文件。"""
        self.path.with_suffix(".json.bak").write_text('{"safe": true}', encoding="utf-8")

        loaded = load_json(self.path, {"safe": False})

        self.assertEqual(loaded, {"safe": False})
        self.assertEqual(load_json(self.path, {}), {"safe": False})

    # 验证failed save keeps previous JSON and removes 临时文件 文件场景下的预期结果。
    def test_failed_save_keeps_previous_json_and_removes_tmp_file(self) -> None:
        """验证failed save keeps previous JSON and removes 临时文件 文件场景下的预期结果。"""
        save_json(self.path, {"version": 1})

        with self.assertRaises(TypeError):
            save_json(self.path, {"bad": {object()}})

        self.assertEqual(load_json(self.path, {}), {"version": 1})
        self.assertEqual(list(self.temp_dir.glob("*.tmp")), [])

    # 验证cleanup 临时文件 JSON files removes leftover 临时文件 files场景下的预期结果。
    def test_cleanup_tmp_json_files_removes_leftover_tmp_files(self) -> None:
        """验证cleanup 临时文件 JSON files removes leftover 临时文件 files场景下的预期结果。"""
        tmp_path = self.temp_dir / "store.json.tmp"
        tmp_path.write_text('{"partial": ', encoding="utf-8")

        cleanup_tmp_json_files(self.temp_dir)

        self.assertFalse(tmp_path.exists())


if __name__ == "__main__":
    unittest.main()
