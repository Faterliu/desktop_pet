"""测试共用的 Qt 应用单例。

Qt 只允许进程内存在一个应用对象。一旦先创建了 QCoreApplication 或 QGuiApplication，
之后任何 QWidget 构造都会触发 “QWidget: Cannot create a QWidget without QApplication”
的致命断言并直接终止进程，unittest 连失败记录都写不出来。因此所有需要 Qt 的测试模块
都必须从这里取应用对象，保证进程内第一个应用就是 QApplication。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP = None

try:
    from PySide6.QtWidgets import QApplication
except ModuleNotFoundError:  # 未安装 PySide6 时由调用方退回仅 QtCore 的替身路径
    QApplication = None


def ensure_app():
    """返回进程内唯一的 Qt 应用对象；首次调用时创建离屏 QApplication。"""
    global APP

    if APP is not None:
        return APP
    if QApplication is not None:
        APP = QApplication.instance() or QApplication([])
    return APP
