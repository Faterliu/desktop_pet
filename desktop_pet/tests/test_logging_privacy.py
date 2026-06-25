from __future__ import annotations

import importlib
import logging
import shutil
import sys
import unittest
from logging.handlers import RotatingFileHandler
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from utils.log_sanitizer import mask_api_key, safe_exception, truncate_text  # noqa: E402


class LoggingPrivacyTests(unittest.TestCase):
    # 准备当前测试所需的环境和数据。
    def setUp(self) -> None:
        """准备当前测试所需的环境和数据。"""
        self.temp_dir = DESKTOP_PET_ROOT / "tmp_work" / "test_logging_privacy" / self._testMethodName
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.root_logger = logging.getLogger()
        self.original_handlers = list(self.root_logger.handlers)
        self.logger_module = importlib.import_module("utils.logger")
        self.original_project_root = self.logger_module.PROJECT_ROOT
        self.original_log_max_bytes = self.logger_module.LOG_MAX_BYTES
        self.original_log_backup_count = self.logger_module.LOG_BACKUP_COUNT
        self.original_configured = self.logger_module._CONFIGURED

    # 清理当前测试产生的环境和数据。
    def tearDown(self) -> None:
        """清理当前测试产生的环境和数据。"""
        for handler in list(self.root_logger.handlers):
            if handler not in self.original_handlers:
                self.root_logger.removeHandler(handler)
                handler.close()
        self.logger_module.PROJECT_ROOT = self.original_project_root
        self.logger_module.LOG_MAX_BYTES = self.original_log_max_bytes
        self.logger_module.LOG_BACKUP_COUNT = self.original_log_backup_count
        self.logger_module._CONFIGURED = self.original_configured
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    # 验证configure logging uses rotating 文件 handler场景下的预期结果。
    def test_configure_logging_uses_rotating_file_handler(self) -> None:
        """验证configure logging uses rotating 文件 handler场景下的预期结果。"""
        logger_module = self.logger_module
        logger_module._CONFIGURED = False
        logger_module.PROJECT_ROOT = self.temp_dir
        logger_module.LOG_MAX_BYTES = 256
        logger_module.LOG_BACKUP_COUNT = 2

        logger_module.configure_logging()
        logging.getLogger("test.logging").info("hello")

        rotating_handlers = [
            handler
            for handler in self.root_logger.handlers
            if isinstance(handler, RotatingFileHandler)
        ]
        self.assertTrue(rotating_handlers)
        self.assertEqual(rotating_handlers[-1].maxBytes, 256)
        self.assertEqual(rotating_handlers[-1].backupCount, 2)
        self.assertTrue((self.temp_dir / "data" / "app.log").exists())

    # 验证log rotation creates 备份 文件场景下的预期结果。
    def test_log_rotation_creates_backup_file(self) -> None:
        """验证log rotation creates 备份 文件场景下的预期结果。"""
        logger_module = self.logger_module
        logger_module._CONFIGURED = False
        logger_module.PROJECT_ROOT = self.temp_dir
        logger_module.LOG_MAX_BYTES = 128
        logger_module.LOG_BACKUP_COUNT = 1

        logger_module.configure_logging()
        logger = logging.getLogger("test.logging.rotation")
        for _ in range(20):
            logger.info("x" * 80)

        for handler in self.root_logger.handlers:
            handler.flush()

        log_dir = self.temp_dir / "data"
        self.assertTrue((log_dir / "app.log").exists())
        self.assertTrue((log_dir / "app.log.1").exists())

    # 验证API 密钥 is masked场景下的预期结果。
    def test_api_key_is_masked(self) -> None:
        """验证API 密钥 is masked场景下的预期结果。"""
        api_key = "sk-1234567890abcdef"

        masked = mask_api_key(api_key)

        self.assertNotIn(api_key, masked)
        self.assertTrue(masked.startswith("sk-1"))
        self.assertTrue(masked.endswith("cdef"))
        self.assertIn("...", masked)

    # 验证exception 文本 masks bearer API 密钥场景下的预期结果。
    def test_exception_text_masks_bearer_api_key(self) -> None:
        """验证exception 文本 masks bearer API 密钥场景下的预期结果。"""
        api_key = "sk-1234567890abcdef"
        exc = RuntimeError(f"Authorization failed: Bearer {api_key}")

        sanitized = safe_exception(exc)

        self.assertNotIn(api_key, sanitized)
        self.assertIn("Bearer sk-1...cdef", sanitized)

    # 验证long 文本 is truncated场景下的预期结果。
    def test_long_text_is_truncated(self) -> None:
        """验证long 文本 is truncated场景下的预期结果。"""
        text = "a" * 100

        truncated = truncate_text(text, max_chars=20)

        self.assertLessEqual(len(truncated), 20)
        self.assertIn("truncated", truncated)


if __name__ == "__main__":
    unittest.main()
