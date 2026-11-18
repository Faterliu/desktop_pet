"""在进程异常退出时落盘诊断信息，供排查原生层崩溃。

Python 的异常钩子只能捕获解释器抛出的错误；Qt、FFmpeg 或堆损坏这类原生崩溃会直接终止
进程，日志里只留下最后一行。这里用 faulthandler 把崩溃时的 Python 栈写入
``data/crash.log``，并把 Qt 自己的告警转进运行日志，使下次崩溃至少留下可分析的现场。
"""

from __future__ import annotations

import faulthandler
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

CRASH_LOG_NAME = "crash.log"
MAX_CRASH_LOG_BYTES = 2_000_000

_LOG_PATH: Path | None = None
_FAULT_FILE = None
_ORIGINAL_EXCEPTHOOK = sys.excepthook
_ORIGINAL_THREAD_HOOK = getattr(threading, "excepthook", None)
_QT_HANDLER_INSTALLED = False


# 超过上限时把旧崩溃日志改名，避免反复崩溃把磁盘写满。
def _rotate(path: Path) -> None:
    """把超过大小上限的崩溃日志改名为 .old。"""
    try:
        if path.is_file() and path.stat().st_size > MAX_CRASH_LOG_BYTES:
            path.replace(path.with_name(f"{path.name}.old"))
    except OSError:
        pass


# 追加一段带时间戳的崩溃记录，写入失败时不影响程序退出流程。
def _append(text: str) -> None:
    """把诊断文本追加到崩溃日志。"""
    if _LOG_PATH is None:
        return
    try:
        with _LOG_PATH.open("a", encoding="utf-8") as file:
            file.write(f"===== {datetime.now().isoformat(timespec='seconds')} =====\n")
            file.write(text)
            if not text.endswith("\n"):
                file.write("\n")
    except OSError:
        pass


# 记录主线程未捕获异常，同时保留 Python 默认的 stderr 输出。
def _handle_exception(exc_type, exc_value, exc_tb) -> None:
    """把主线程未捕获异常写入崩溃日志，再交给原始钩子。"""
    try:
        _append(
            f"[excepthook] thread=main\n"
            + "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        )
    finally:
        _ORIGINAL_EXCEPTHOOK(exc_type, exc_value, exc_tb)


# 记录后台线程未捕获异常，线程名用于区分聊天、摘要与解码任务。
def _handle_thread_exception(args) -> None:
    """把后台线程未捕获异常写入崩溃日志，再交给原始钩子。"""
    try:
        name = getattr(args.thread, "name", "unknown")
        _append(
            f"[excepthook] thread={name}\n"
            + "".join(
                traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
            )
        )
    finally:
        if _ORIGINAL_THREAD_HOOK is not None:
            _ORIGINAL_THREAD_HOOK(args)


# 启用崩溃捕获，返回本次使用的日志路径。
def install_crash_reporting(data_dir: Path) -> Path:
    """启用 faulthandler 与异常钩子，崩溃栈统一追加到 data/crash.log。"""
    global _LOG_PATH, _FAULT_FILE

    path = Path(data_dir) / CRASH_LOG_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    if _LOG_PATH != path and _FAULT_FILE is not None:
        # 切换到新的日志路径时先释放旧文件，避免两个句柄同时指向已改名文件。
        try:
            faulthandler.disable()
            _FAULT_FILE.close()
        except (OSError, ValueError):
            pass
        _FAULT_FILE = None
    _LOG_PATH = path
    _rotate(path)

    if _FAULT_FILE is None:
        _FAULT_FILE = path.open("a", encoding="utf-8")
        faulthandler.enable(file=_FAULT_FILE, all_threads=True)
    sys.excepthook = _handle_exception
    if _ORIGINAL_THREAD_HOOK is not None:
        threading.excepthook = _handle_thread_exception
    return path


# 停止崩溃捕获并关闭日志文件，仅在测试或重定向日志路径时使用。
def uninstall_crash_reporting() -> None:
    """关闭 faulthandler 并恢复默认异常钩子。"""
    global _FAULT_FILE

    try:
        faulthandler.disable()
    except (OSError, ValueError):
        pass
    if _FAULT_FILE is not None:
        try:
            _FAULT_FILE.close()
        except (OSError, ValueError):
            pass
        _FAULT_FILE = None
    sys.excepthook = _ORIGINAL_EXCEPTHOOK
    if _ORIGINAL_THREAD_HOOK is not None:
        threading.excepthook = _ORIGINAL_THREAD_HOOK


# 把 Qt 消息按级别转发到 qt 日志，调试类消息保持静默。
def _qt_message_handler(mode, context, message) -> None:
    """转发一条 Qt 消息到运行日志。"""
    try:
        from PySide6.QtCore import QtMsgType
    except ModuleNotFoundError:
        return
    from utils.logger import get_logger

    levels = {
        QtMsgType.QtWarningMsg: get_logger("qt").warning,
        QtMsgType.QtCriticalMsg: get_logger("qt").error,
        QtMsgType.QtFatalMsg: get_logger("qt").critical,
    }
    emit = levels.get(mode)
    if emit is None:
        return
    category = getattr(context, "category", "") or "qt"
    emit("[%s] %s", category, message)


# 把 Qt 的告警、严重错误与致命错误写进运行日志，控件类名随消息一起记录。
def install_qt_message_handler() -> bool:
    """安装 Qt 消息处理器，把 Qt 自身告警转进运行日志。"""
    global _QT_HANDLER_INSTALLED

    if _QT_HANDLER_INSTALLED:
        return True
    try:
        from PySide6.QtCore import qInstallMessageHandler
    except ModuleNotFoundError:
        return False

    qInstallMessageHandler(_qt_message_handler)
    _QT_HANDLER_INSTALLED = True
    return True
