from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QRegion
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from utils.dwm_border import apply_transparent_window_fixes, suppress_dwm_border


def _find_bubble_position(
    bubble_width: int,
    bubble_height: int,
    anchor_rect: QRect,
    candidates: list[QPoint],
    exclusion_rects: list[QRect] | None = None,
) -> QPoint:
    """从候选位置中选取第一个完全在屏幕内且不与角色窗口重叠的位置。

    所有候选都不满足时，将首选位置 clamp 到屏幕可用区域内。
    exclusion_rects 为额外的避让区域（如另一个可见气泡的几何）。
    """
    screen = QApplication.screenAt(anchor_rect.center())
    if screen is None:
        screen = QApplication.primaryScreen()
    if screen is None:
        return candidates[0] if candidates else QPoint(0, 0)

    available = screen.availableGeometry()
    _exclusions = exclusion_rects or []

    for pos in candidates:
        bubble_rect = QRect(pos.x(), pos.y(), bubble_width, bubble_height)
        if not available.contains(bubble_rect):
            continue
        if bubble_rect.intersects(anchor_rect):
            continue
        if any(bubble_rect.intersects(ex) for ex in _exclusions):
            continue
        return pos

    first = candidates[0]
    x = max(available.x(), min(first.x(), available.x() + available.width() - bubble_width))
    y = max(available.y(), min(first.y(), available.y() + available.height() - bubble_height))
    return QPoint(max(0, x), max(0, y))


class SpeechBubble(QWidget):
    def __init__(self) -> None:
        """初始化悬浮气泡窗口与自动关闭计时器。"""
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("SpeechBubble { background: transparent; border: none; }")

        self.label = QLabel(self)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(
            "QLabel { color: #3d2a1b; font-size: 13px; background: transparent; }"
        )
        self.label.move(16, 12)

        self.close_timer = QTimer(self)
        self.close_timer.setSingleShot(True)
        self.close_timer.timeout.connect(self.hide)

        self.source = "system"
        self._last_anchor_rect = QRect()
        self._always_on_top = True

    def set_always_on_top(self, enabled: bool) -> None:
        """同步气泡窗口的置顶状态与主窗口一致。"""
        if self._always_on_top == enabled:
            return
        self._always_on_top = enabled
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if was_visible:
            self.hide()
        if was_visible:
            self.show()
        apply_transparent_window_fixes(self)

    def nativeEvent(self, eventType, message) -> tuple:  # noqa: N802
        """移除 Windows DWM 在透明无边框窗口周围绘制的细线边框。"""
        ok, result = suppress_dwm_border(eventType, message)
        if ok:
            return True, result
        return super().nativeEvent(eventType, message)

    def showEvent(self, event) -> None:  # noqa: N802
        """窗口显示后再次应用形状和 Windows 透明窗口修正。"""
        super().showEvent(event)
        self._apply_bubble_mask()
        apply_transparent_window_fixes(self)

    def show_message(
        self,
        text: str,
        anchor_rect: QRect,
        duration_ms: int,
        source: str = "system",
    ) -> None:
        """在宠物附近显示一条气泡消息，并按时自动关闭。"""
        self.source = source
        self.label.setText(text)
        self.label.adjustSize()
        width = min(max(self.label.sizeHint().width() + 32, 180), 360)
        self.label.setFixedWidth(width - 32)
        self.label.adjustSize()
        height = self.label.height() + 28
        self.resize(width, height)
        self._apply_bubble_mask()
        self._last_anchor_rect = QRect(anchor_rect)
        self.reposition(anchor_rect)
        self.show()
        self._apply_bubble_mask()
        apply_transparent_window_fixes(self)
        self.raise_()
        self.close_timer.start(duration_ms)

    def reposition(
        self,
        anchor_rect: QRect | None = None,
        exclusion_rects: list[QRect] | None = None,
    ) -> None:
        """根据角色当前位置，在屏幕内找到不覆盖角色和其他气泡的最佳位置。"""
        if anchor_rect is not None:
            self._last_anchor_rect = QRect(anchor_rect)
        if self._last_anchor_rect.isNull():
            return

        a = self._last_anchor_rect
        bw = self.width()
        bh = self.height()
        candidates = [
            QPoint(a.x() + a.width() - bw + 20, a.y() - bh - 10),
            QPoint(a.x() - 20, a.y() - bh - 10),
            QPoint(a.x() + a.width() - bw + 20, a.y() + a.height() + 10),
            QPoint(a.x() - 20, a.y() + a.height() + 10),
            QPoint(a.x() + a.width() + 10, a.y() + a.height() // 2 - bh // 2),
            QPoint(a.x() - bw - 10, a.y() + a.height() // 2 - bh // 2),
        ]
        self.move(_find_bubble_position(bw, bh, a, candidates, exclusion_rects))

    def paintEvent(self, event) -> None:  # noqa: N802
        """绘制圆角气泡背景和底部小尾巴。"""
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = self._bubble_path()
        painter.fillPath(path, QColor("#fff3d7"))
        painter.setPen(QColor("#d8b27a"))
        painter.drawPath(path)

    def _bubble_path(self) -> QPainterPath:
        """返回气泡主体和尾巴的轮廓，供绘制和窗口裁剪共用。"""
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height() - 8, 18, 18)
        path.moveTo(self.width() - 44, self.height() - 8)
        path.lineTo(self.width() - 32, self.height())
        path.lineTo(self.width() - 20, self.height() - 8)
        path.closeSubpath()
        return path

    def _apply_bubble_mask(self) -> None:
        """按气泡轮廓裁剪窗口，避免系统沿矩形外接框补边。"""
        region = QRegion(self._bubble_path().toFillPolygon().toPolygon())
        self.setMask(region)


class ReplyBubble(QWidget):
    """知识问候右侧独立应答气泡：可点击、无尾巴、不指向角色。"""

    clicked = Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAutoFillBackground(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.label = QLabel(self)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(
            "QLabel { color: #3d2a1b; font-size: 13px; background: transparent; }"
        )
        self.label.move(14, 10)

        self.close_timer = QTimer(self)
        self.close_timer.setSingleShot(True)
        self.close_timer.timeout.connect(self.hide)

        self._anchor_rect = QRect()

    def set_always_on_top(self, enabled: bool) -> None:
        """同步气泡窗口置顶状态。"""
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if was_visible:
            self.hide()
        if was_visible:
            self.show()
        apply_transparent_window_fixes(self)

    def nativeEvent(self, eventType, message) -> tuple:  # noqa: N802
        """移除 Windows DWM 在透明无边框窗口周围绘制的细线边框。"""
        ok, result = suppress_dwm_border(eventType, message)
        if ok:
            return True, result
        return super().nativeEvent(eventType, message)

    def showEvent(self, event) -> None:  # noqa: N802
        """窗口显示后应用形状和透明修正。"""
        super().showEvent(event)
        self._apply_mask()
        apply_transparent_window_fixes(self)

    def show_message(
        self,
        text: str,
        anchor_rect: QRect,
        duration_ms: int,
    ) -> None:
        """在角色右侧显示可点击的应答气泡。"""
        self.label.setText(text)
        self.label.adjustSize()
        width = min(max(self.label.sizeHint().width() + 28, 120), 280)
        self.label.setFixedWidth(width - 28)
        self.label.adjustSize()
        height = self.label.height() + 20
        self.resize(width, height)
        self._apply_mask()
        self._anchor_rect = QRect(anchor_rect)
        self.show()
        self._reposition()
        self._apply_mask()
        apply_transparent_window_fixes(self)
        self.raise_()
        self.close_timer.start(duration_ms)

    def reposition(
        self,
        anchor_rect: QRect,
        exclusion_rects: list[QRect] | None = None,
    ) -> None:
        """更新锚点并重新摆放气泡位置，可传入其他气泡作为避让区域。"""
        self._anchor_rect = QRect(anchor_rect)
        self._reposition(exclusion_rects)

    def _reposition(
        self,
        exclusion_rects: list[QRect] | None = None,
    ) -> None:
        """在角色四周找到屏幕内不覆盖角色和其他气泡的最佳应答气泡位置。"""
        if self._anchor_rect.isNull():
            return
        a = self._anchor_rect
        bw = self.width()
        bh = self.height()
        cx = a.x() + a.width() // 2
        cy = a.y() + a.height() // 2
        candidates = [
            QPoint(a.x() + a.width() + 12, cy - bh // 2),
            QPoint(a.x() - bw - 12, cy - bh // 2),
            QPoint(cx - bw // 2, a.y() - bh - 10),
            QPoint(cx - bw // 2, a.y() + a.height() + 10),
        ]
        self.move(_find_bubble_position(bw, bh, a, candidates, exclusion_rects))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        """点击气泡视为用户回应知识问候。"""
        self.clicked.emit()
        self.hide()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        """绘制圆角矩形气泡（无尾巴）。"""
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 14, 14)
        painter.fillPath(path, QColor("#e8f5e9"))
        painter.setPen(QColor("#81c784"))
        painter.drawPath(path)

    def _apply_mask(self) -> None:
        """按圆角矩形裁剪窗口。"""
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 14, 14)
        region = QRegion(path.toFillPolygon().toPolygon())
        self.setMask(region)
