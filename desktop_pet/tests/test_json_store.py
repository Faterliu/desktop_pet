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
    def setUp(self) -> None:
        self.temp_dir = DESKTOP_PET_ROOT / "tmp_work" / "test_json_store" / self._testMethodName
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.temp_dir / "store.json"

    def tearDown(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_load_json_creates_missing_file_from_default(self) -> None:
        default = {"items": []}

        loaded = load_json(self.path, default)
        loaded["items"].append("changed")

        self.assertEqual(load_json(self.path, {}), {"items": []})
        self.assertEqual(default, {"items": []})

    def test_ensure_json_file_creates_missing_file(self) -> None:
        ensured = ensure_json_file(self.path, {"ready": True})

        self.assertEqual(ensured, self.path)
        self.assertEqual(load_json(self.path, {}), {"ready": True})

    def test_save_json_writes_valid_json_and_preserves_backup(self) -> None:
        save_json(self.path, {"version": 1})
        save_json(self.path, {"version": 2})

        self.assertEqual(load_json(self.path, {}), {"version": 2})
        self.assertEqual(load_json(self.path.with_suffix(".json.bak"), {}), {"version": 1})

    def test_load_json_recovers_from_backup_when_primary_is_corrupt(self) -> None:
        save_json(self.path.with_suffix(".json.bak"), {"safe": True})
        self.path.write_text('{"broken": ', encoding="utf-8")

        loaded = load_json(self.path, {"safe": False})

        self.assertEqual(loaded, {"safe": True})
        self.assertFalse(self.path.exists())
        self.assertEqual(len(list(self.temp_dir.glob("store.json.corrupt.*"))), 1)

    def test_load_json_returns_deepcopy_default_when_primary_and_backup_are_corrupt(self) -> None:
        default = {"items": []}
        self.path.write_text('{"broken": ', encoding="utf-8")
        self.path.with_suffix(".json.bak").write_text('{"also_broken": ', encoding="utf-8")

        loaded = load_json(self.path, default)
        loaded["items"].append("changed")

        self.assertEqual(default, {"items": []})
        self.assertEqual(len(list(self.temp_dir.glob("store.json.corrupt.*"))), 1)

    def test_failed_save_keeps_previous_json_and_removes_tmp_file(self) -> None:
        save_json(self.path, {"version": 1})

        with self.assertRaises(TypeError):
            save_json(self.path, {"bad": {object()}})

        self.assertEqual(load_json(self.path, {}), {"version": 1})
        self.assertEqual(list(self.temp_dir.glob("*.tmp")), [])

    def test_cleanup_tmp_json_files_removes_leftover_tmp_files(self) -> None:
        tmp_path = self.temp_dir / "store.json.tmp"
        tmp_path.write_text('{"partial": ', encoding="utf-8")

        cleanup_tmp_json_files(self.temp_dir)

        self.assertFalse(tmp_path.exists())


if __name__ == "__main__":
    unittest.main()
