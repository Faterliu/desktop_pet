"""崩溃捕获与 Qt 消息转发的回归测试。"""

from __future__ import annotations

import faulthandler
import shutil
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils import crash_reporter  # noqa: E402


class CrashReporterTests(unittest.TestCase):
    # 每个用例使用独立目录，避免污染 data/ 下的真实崩溃日志。
    def setUp(self) -> None:
        """准备临时数据目录并记录原始异常钩子。"""
        # 与其余测试一致，临时目录放在仓库内的 tmp_work。
        self.data_dir = ROOT / "tmp_work" / "test_crash_reporter" / self._testMethodName / "data"
        shutil.rmtree(self.data_dir, ignore_errors=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._original_hook = crash_reporter._ORIGINAL_EXCEPTHOOK
        self._original_thread_hook = crash_reporter._ORIGINAL_THREAD_HOOK

    def tearDown(self) -> None:
        """恢复钩子并关闭本次打开的崩溃日志。"""
        crash_reporter._ORIGINAL_EXCEPTHOOK = self._original_hook
        crash_reporter._ORIGINAL_THREAD_HOOK = self._original_thread_hook
        crash_reporter.uninstall_crash_reporting()

    # 安装后应生成日志文件、启用 faulthandler 并接管主线程异常。
    def test_install_creates_log_and_enables_faulthandler(self) -> None:
        """验证安装结果包含日志文件、faulthandler 与异常钩子。"""
        path = crash_reporter.install_crash_reporting(self.data_dir)

        self.assertTrue(path.is_file())
        self.assertEqual(path.name, crash_reporter.CRASH_LOG_NAME)
        self.assertEqual(path.parent, self.data_dir)
        self.assertTrue(faulthandler.is_enabled())
        self.assertIs(sys.excepthook, crash_reporter._handle_exception)

    # 主线程未捕获异常应记录线程名与异常信息。
    def test_uncaught_exception_is_written_to_log(self) -> None:
        """验证主线程异常写入 crash.log。"""
        path = crash_reporter.install_crash_reporting(self.data_dir)
        crash_reporter._ORIGINAL_EXCEPTHOOK = lambda *_args: None

        try:
            raise RuntimeError("boom")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())

        text = path.read_text(encoding="utf-8")
        self.assertIn("[excepthook] thread=main", text)
        self.assertIn("RuntimeError: boom", text)

    # 后台线程异常应记录线程名，便于区分聊天与解码任务。
    def test_thread_exception_is_written_with_thread_name(self) -> None:
        """验证后台线程异常写入 crash.log。"""
        path = crash_reporter.install_crash_reporting(self.data_dir)
        crash_reporter._ORIGINAL_THREAD_HOOK = lambda _args: None

        try:
            raise ValueError("thread boom")
        except ValueError:
            exc_type, exc_value, exc_tb = sys.exc_info()
        args = SimpleNamespace(
            exc_type=exc_type,
            exc_value=exc_value,
            exc_traceback=exc_tb,
            thread=SimpleNamespace(name="video:7"),
        )
        crash_reporter._handle_thread_exception(args)

        text = path.read_text(encoding="utf-8")
        self.assertIn("[excepthook] thread=video:7", text)
        self.assertIn("ValueError: thread boom", text)

    # 超过大小上限时把旧日志改名，保证新日志可写。
    def test_oversized_log_is_rotated(self) -> None:
        """验证过大日志被改名为 .old。"""
        path = crash_reporter.install_crash_reporting(self.data_dir)
        crash_reporter.uninstall_crash_reporting()
        path.write_text("x" * (crash_reporter.MAX_CRASH_LOG_BYTES + 1), encoding="utf-8")

        crash_reporter.install_crash_reporting(self.data_dir)

        self.assertTrue(path.with_name(f"{path.name}.old").is_file())
        self.assertLess(path.stat().st_size, 1024)

    # 重复安装不应重复接管钩子或反复打开文件。
    def test_install_is_idempotent(self) -> None:
        """验证重复安装返回同一路径且钩子保持一致。"""
        first = crash_reporter.install_crash_reporting(self.data_dir)
        second = crash_reporter.install_crash_reporting(self.data_dir)

        self.assertEqual(first, second)
        self.assertIs(sys.excepthook, crash_reporter._handle_exception)

    # Qt 告警应带上日志分类进入 qt 日志。
    def test_qt_warning_is_forwarded_with_category(self) -> None:
        """验证 Qt 告警被转发到 qt 日志并保留分类。"""
        from PySide6.QtCore import QtMsgType

        with self.assertLogs("qt", level="WARNING") as captured:
            crash_reporter._qt_message_handler(
                QtMsgType.QtWarningMsg,
                SimpleNamespace(category="qt.qpa.fonts"),
                "QFont::setPointSize: Point size <= 0 (-1)",
            )

        self.assertIn("qt.qpa.fonts", captured.output[0])
        self.assertIn("Point size <= 0", captured.output[0])

    # 调试类消息不写入日志，避免启动噪声。
    def test_qt_debug_message_is_ignored(self) -> None:
        """验证 Qt 调试消息不进入日志。"""
        from PySide6.QtCore import QtMsgType

        with self.assertNoLogs("qt", level="DEBUG"):
            crash_reporter._qt_message_handler(
                QtMsgType.QtDebugMsg,
                SimpleNamespace(category="qt"),
                "ignored debug message",
            )


if __name__ == "__main__":
    unittest.main()
