from __future__ import annotations

import builtins
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from ai.mem0_memory_service import Mem0MemoryService  # noqa: E402


class Mem0MemoryServiceTests(unittest.TestCase):
    # 验证enabled mem 0 without DashScope 密钥 skips import and init场景下的预期结果。
    def test_enabled_mem0_without_dashscope_key_skips_import_and_init(self) -> None:
        """验证enabled mem 0 without DashScope 密钥 skips import and init场景下的预期结果。"""
        config = {
            "api": {"deepseek": {"api_key": "deepseek-key"}},
            "memory": {
                "enable_mem0": True,
                "dashscope_api_key": "",
                "dashscope_api_key_env": "DESKTOP_PET_TEST_MISSING_DASHSCOPE_KEY",
            },
        }

        real_import = builtins.__import__
        mem0_import_attempted = False

        # 为测试准备failifmem0imported数据或断言辅助结果。
        def fail_if_mem0_imported(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            """为测试准备failifmem0imported数据或断言辅助结果。"""
            nonlocal mem0_import_attempted
            if name == "mem0":
                mem0_import_attempted = True
                raise ImportError("mem0 should not be imported without an embedding key")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=fail_if_mem0_imported):
            service = Mem0MemoryService(config)

        self.assertFalse(service.is_available())
        self.assertFalse(mem0_import_attempted)

    # 验证 Mem0 LLM 读取嵌套 DeepSeek 配置，不再读取旧扁平 API 字段。
    def test_mem0_llm_uses_nested_deepseek_config(self) -> None:
        """验证 Mem0 LLM 读取嵌套 DeepSeek 配置。"""
        config = {
            "api": {
                "deepseek": {
                    "api_key": "deepseek-key",
                    "base_url": "https://deepseek.test",
                    "model": "deepseek-test",
                }
            },
            "memory": {
                "dashscope_api_key": "dashscope-key",
                "dashscope_embedding_dimensions": 8,
            },
        }
        service = object.__new__(Mem0MemoryService)
        with tempfile.TemporaryDirectory() as temp:
            with patch("ai.mem0_memory_service.PROJECT_ROOT", Path(temp)):
                mem0_config = service._build_mem0_config(config)

        llm = mem0_config["llm"]
        self.assertEqual(llm["provider"], "deepseek")
        self.assertEqual(llm["config"]["model"], "deepseek-test")
        self.assertEqual(llm["config"]["deepseek_base_url"], "https://deepseek.test")
        self.assertNotIn("openai_base_url", llm["config"])


if __name__ == "__main__":
    unittest.main()
