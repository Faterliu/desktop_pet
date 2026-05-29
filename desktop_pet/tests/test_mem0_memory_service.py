from __future__ import annotations

import builtins
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from ai.mem0_memory_service import Mem0MemoryService  # noqa: E402


class Mem0MemoryServiceTests(unittest.TestCase):
    def test_enabled_mem0_without_dashscope_key_skips_import_and_init(self) -> None:
        config = {
            "api": {"api_key": "deepseek-key"},
            "memory": {
                "enable_mem0": True,
                "dashscope_api_key": "",
                "dashscope_api_key_env": "DESKTOP_PET_TEST_MISSING_DASHSCOPE_KEY",
            },
        }

        real_import = builtins.__import__
        mem0_import_attempted = False

        def fail_if_mem0_imported(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal mem0_import_attempted
            if name == "mem0":
                mem0_import_attempted = True
                raise ImportError("mem0 should not be imported without an embedding key")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=fail_if_mem0_imported):
            service = Mem0MemoryService(config)

        self.assertFalse(service.is_available())
        self.assertFalse(mem0_import_attempted)


if __name__ == "__main__":
    unittest.main()
