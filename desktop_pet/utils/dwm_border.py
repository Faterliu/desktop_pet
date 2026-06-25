"""消除 Windows DWM 在无边框透明窗口周围绘制的细线边框。"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


_WM_NCCALCSIZE = 0x0083
_GWL_EXSTYLE = -20
_WS_EX_DLGMODALFRAME = 0x00000001
_WS_EX_CLIENTEDGE = 0x00000200
_WS_EX_STATICEDGE = 0x00020000
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_FRAMECHANGED = 0x0020

_DWMWA_NCRENDERING_POLICY = 2
_DWMNCRP_DISABLED = 1
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_DONOTROUND = 1
_DWMWA_BORDER_COLOR = 34
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36
_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMSBT_NONE = 1
_DWMWA_COLOR_NONE = 0xFFFFFFFE


# 在 nativeEvent 中调用，移除 Windows DWM 为无边框窗口添加的边框。
def suppress_dwm_border(event_type: object, message: object) -> tuple[bool, int]:
    """在 nativeEvent 中调用，移除 Windows DWM 为无边框窗口添加的边框。

    用法:
        def nativeEvent(self, eventType, message):
            ok, result = suppress_dwm_border(eventType, message)
            if ok:
                return True, result
            return super().nativeEvent(eventType, message)
    """
    if sys.platform != "win32":
        return False, 0

    # PySide6 的 eventType 可能是 QByteArray 或 bytes
    et = event_type.data().decode("utf-8") if hasattr(event_type, "data") else str(event_type)
    if et != "windows_generic_MSG":
        return False, 0

    # message 在 PySide6 中可能是 sip.voidptr，需先转为 int
    try:
        msg_ptr = int(message)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False, 0

    msg = ctypes.cast(msg_ptr, ctypes.POINTER(_MSG)).contents
    if msg.message == _WM_NCCALCSIZE:
        return True, 0
    return False, 0


# 对透明无边框窗口应用 Windows 侧修正，移除矩形边框、圆角和系统背景。
def apply_transparent_window_fixes(widget: object) -> None:
    """对透明无边框窗口应用 Windows 侧修正，移除矩形边框、圆角和系统背景。"""
    if sys.platform != "win32":
        return

    try:
        hwnd = int(widget.winId())  # type: ignore[attr-defined]
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return

    _remove_extended_edge_styles(hwnd)
    _set_dwm_int_attribute(hwnd, _DWMWA_NCRENDERING_POLICY, _DWMNCRP_DISABLED)
    _set_dwm_int_attribute(hwnd, _DWMWA_WINDOW_CORNER_PREFERENCE, _DWMWCP_DONOTROUND)
    _set_dwm_int_attribute(hwnd, _DWMWA_SYSTEMBACKDROP_TYPE, _DWMSBT_NONE)
    _set_dwm_color_attribute(hwnd, _DWMWA_BORDER_COLOR, _DWMWA_COLOR_NONE)
    _set_dwm_color_attribute(hwnd, _DWMWA_CAPTION_COLOR, _DWMWA_COLOR_NONE)
    _set_dwm_color_attribute(hwnd, _DWMWA_TEXT_COLOR, _DWMWA_COLOR_NONE)


# 去掉可能让窗口出现浅色外框的扩展边缘样式。
def _remove_extended_edge_styles(hwnd: int) -> None:
    """去掉可能让窗口出现浅色外框的扩展边缘样式。"""
    try:
        user32 = ctypes.windll.user32
        get_window_long = user32.GetWindowLongPtrW
        set_window_long = user32.SetWindowLongPtrW
        get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
        get_window_long.restype = ctypes.c_void_p
        set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        set_window_long.restype = ctypes.c_void_p

        current = int(get_window_long(wintypes.HWND(hwnd), _GWL_EXSTYLE) or 0)
        cleaned = current & ~(_WS_EX_DLGMODALFRAME | _WS_EX_CLIENTEDGE | _WS_EX_STATICEDGE)
        if cleaned == current:
            return

        set_window_long(wintypes.HWND(hwnd), _GWL_EXSTYLE, ctypes.c_void_p(cleaned))
        user32.SetWindowPos(
            wintypes.HWND(hwnd),
            None,
            0,
            0,
            0,
            0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_NOACTIVATE | _SWP_FRAMECHANGED,
        )
    except (AttributeError, OSError):
        return


# 设置 DWM 整数属性；旧系统不支持时静默跳过。
def _set_dwm_int_attribute(hwnd: int, attribute: int, value: int) -> None:
    """设置 DWM 整数属性；旧系统不支持时静默跳过。"""
    try:
        raw_value = ctypes.c_int(value)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(attribute),
            ctypes.byref(raw_value),
            ctypes.sizeof(raw_value),
        )
    except OSError:
        return


# 使用 Windows API 直接设置窗口的 WS_EX_TOPMOST 样式并调整 Z-order。
def force_window_topmost(hwnd: int, enabled: bool = True) -> None:
    """使用 Windows API 直接设置窗口的 WS_EX_TOPMOST 样式并调整 Z-order。

    Qt 的 WindowStaysOnTopHint 在频繁 setMask/resize 的透明分层窗口上可能被
    Windows 系统清除，此函数直接操作原生 HWND 确保置顶生效。
    """
    if sys.platform != "win32":
        return

    try:
        user32 = ctypes.windll.user32
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOACTIVATE = 0x0010
        hwnd_insert = wintypes.HWND(HWND_TOPMOST if enabled else HWND_NOTOPMOST)
        user32.SetWindowPos(
            wintypes.HWND(hwnd),
            hwnd_insert,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
    except (AttributeError, OSError):
        return


# 设置 DWM 颜色属性；用于声明边框、标题栏等颜色不存在。
def _set_dwm_color_attribute(hwnd: int, attribute: int, value: int) -> None:
    """设置 DWM 颜色属性；用于声明边框、标题栏等颜色不存在。"""
    try:
        raw_value = ctypes.c_uint(value)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(attribute),
            ctypes.byref(raw_value),
            ctypes.sizeof(raw_value),
        )
    except OSError:
        return
