from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget


# 判断规范化后的框选矩形是否达到最小边长。
def is_valid_selection(selection: QRect, minimum_size: int) -> bool:
    """返回选区宽高是否都达到最小逻辑像素要求。"""
    normalized = selection.normalized()
    limit = max(1, int(minimum_size))
    return normalized.width() >= limit and normalized.height() >= limit


class ScreenshotSelectionOverlay(QWidget):
    """在冻结的单屏截图上提供鼠标框选交互。"""

    selection_confirmed = Signal(QRect, QSize)
    cancelled = Signal()

    # 初始化覆盖目标屏幕的静态截图浮层。
    def __init__(
        self,
        screenshot: QPixmap,
        screen_geometry: QRect,
        *,
        minimum_size: int = 12,
    ) -> None:
        """保存冻结截图并设置无边框置顶框选窗口。"""
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.screenshot = screenshot
        self.minimum_size = max(1, int(minimum_size))
        self._drag_start = QPoint()
        self._selection = QRect()
        self._dragging = False
        self._completed = False
        self.setGeometry(screen_geometry)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

    # 显示后立即获取键盘焦点，以便 Esc 可以取消。
    def showEvent(self, event) -> None:  # noqa: N802
        """显示框选浮层并获取输入焦点。"""
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    # 绘制冻结屏幕、暗色遮罩、明亮选区和操作提示。
    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        """绘制静态截图和当前鼠标选择区域。"""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(self.rect(), self.screenshot, self.screenshot.rect())
        painter.fillRect(self.rect(), QColor(0, 0, 0, 115))

        selected = self._selection.normalized().intersected(self.rect())
        if not selected.isEmpty():
            painter.save()
            painter.setClipRect(selected)
            painter.drawPixmap(self.rect(), self.screenshot, self.screenshot.rect())
            painter.restore()
            painter.setPen(QPen(QColor("#ffcf70"), 2))
            painter.drawRect(selected.adjusted(0, 0, -1, -1))

        painter.setPen(QColor("white"))
        painter.drawText(
            QRect(20, 16, max(0, self.width() - 40), 36),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "拖动鼠标框选截图区域 · Esc 或右键取消",
        )

    # 左键开始框选，右键立即取消。
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """处理框选起点或右键取消。"""
        if event.button() == Qt.MouseButton.RightButton:
            self._cancel()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
            self._selection = QRect(self._drag_start, self._drag_start)
            self._dragging = True
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    # 拖动鼠标时实时更新规范化选区。
    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """更新当前框选矩形。"""
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self._selection = QRect(self._drag_start, event.position().toPoint()).normalized()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    # 左键释放时确认足够大的区域，过小区域允许重新选择。
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """确认有效选区并发出逻辑坐标与视口尺寸。"""
        if event.button() != Qt.MouseButton.LeftButton or not self._dragging:
            super().mouseReleaseEvent(event)
            return
        self._dragging = False
        selected = QRect(self._drag_start, event.position().toPoint()).normalized()
        selected = selected.intersected(self.rect())
        if not is_valid_selection(selected, self.minimum_size):
            self._selection = QRect()
            self.update()
            event.accept()
            return
        self._selection = selected
        self._completed = True
        self.hide()
        self.selection_confirmed.emit(QRect(selected), QSize(self.size()))
        event.accept()

    # Esc 取消当前截图流程。
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        """处理键盘取消操作。"""
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            event.accept()
            return
        super().keyPressEvent(event)

    # 系统关闭浮层时也视为取消，防止桌宠窗口保持隐藏。
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """把非确认路径的窗口关闭统一转换为取消信号。"""
        if not self._completed:
            self._completed = True
            self.cancelled.emit()
        super().closeEvent(event)

    # 只发出一次取消信号并关闭浮层。
    def _cancel(self) -> None:
        """终止框选并释放浮层。"""
        if self._completed:
            return
        self._completed = True
        self.cancelled.emit()
        self.close()
