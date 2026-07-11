from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QPixmap


class ScreenshotCaptureError(RuntimeError):
    """截图获取或内存编码失败。"""


@dataclass(frozen=True)
class CapturedScreenshot:
    """仅在内存中传递的截图数据。"""

    image_bytes: bytes
    mime_type: str


class ScreenshotCaptureService:
    """截取指定屏幕并编码为受大小限制的内存图片。"""

    # 截取指定屏幕，缩放后优先编码为 PNG，过大时回退为 JPEG。
    def capture_screen(
        self,
        screen: Any,
        *,
        max_image_edge: int = 2048,
        max_image_bytes: int = 6 * 1024 * 1024,
    ) -> CapturedScreenshot:
        """截取指定屏幕并返回不落盘的图片字节。"""
        pixmap = self.grab_screen_pixmap(screen)
        return self.encode_pixmap(
            pixmap,
            max_image_edge=max_image_edge,
            max_image_bytes=max_image_bytes,
        )

    # 获取指定屏幕的原始快照，供全屏编码或静态框选共用。
    def grab_screen_pixmap(self, screen: Any) -> QPixmap:
        """截取指定屏幕并校验结果，不执行缩放或编码。"""
        if screen is None:
            raise ScreenshotCaptureError("没有找到可截图的屏幕。")
        pixmap = screen.grabWindow(0)
        if pixmap is None or pixmap.isNull():
            raise ScreenshotCaptureError("截图失败，没有获取到屏幕图像。")
        return pixmap

    # 将浮层逻辑坐标映射到原始截图像素，并返回裁剪后的图像。
    def crop_pixmap(
        self,
        pixmap: QPixmap,
        selection_rect: QRect,
        viewport_size: QSize,
    ) -> QPixmap:
        """按浮层视口坐标裁剪截图，兼容高 DPI 缩放。"""
        if pixmap is None or pixmap.isNull():
            raise ScreenshotCaptureError("截图内容为空，无法裁剪。")
        viewport_width = viewport_size.width()
        viewport_height = viewport_size.height()
        if viewport_width <= 0 or viewport_height <= 0:
            raise ScreenshotCaptureError("截图框选区域尺寸无效。")

        viewport_rect = QRect(QPoint(0, 0), viewport_size)
        selected = selection_rect.normalized().intersected(viewport_rect)
        if selected.width() <= 0 or selected.height() <= 0:
            raise ScreenshotCaptureError("没有选择有效的截图区域。")

        scale_x = pixmap.width() / viewport_width
        scale_y = pixmap.height() / viewport_height
        left = int(selected.left() * scale_x)
        top = int(selected.top() * scale_y)
        right = int((selected.x() + selected.width()) * scale_x + 0.999999)
        bottom = int((selected.y() + selected.height()) * scale_y + 0.999999)
        source_rect = QRect(
            left,
            top,
            max(1, right - left),
            max(1, bottom - top),
        ).intersected(pixmap.rect())
        cropped = pixmap.copy(source_rect)
        if cropped.isNull():
            raise ScreenshotCaptureError("截图区域裁剪失败。")
        return cropped

    # 将 QPixmap 缩放并编码，便于无真实屏幕的单元测试复用。
    def encode_pixmap(
        self,
        pixmap: QPixmap,
        *,
        max_image_edge: int = 2048,
        max_image_bytes: int = 6 * 1024 * 1024,
    ) -> CapturedScreenshot:
        """把有效 QPixmap 编码为 PNG，超限时改用 JPEG 85。"""
        if pixmap is None or pixmap.isNull():
            raise ScreenshotCaptureError("截图失败，没有获取到屏幕图像。")
        edge_limit = max(1, int(max_image_edge))
        byte_limit = max(1, int(max_image_bytes))
        largest_edge = max(pixmap.width(), pixmap.height())
        if largest_edge > edge_limit:
            pixmap = pixmap.scaled(
                edge_limit,
                edge_limit,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        png_bytes = self._encode(pixmap, "PNG")
        if len(png_bytes) <= byte_limit:
            return CapturedScreenshot(png_bytes, "image/png")

        jpeg_bytes = self._encode(pixmap, "JPEG", quality=85)
        if len(jpeg_bytes) > byte_limit:
            raise ScreenshotCaptureError("截图压缩后仍然过大，暂时无法上传解析。")
        return CapturedScreenshot(jpeg_bytes, "image/jpeg")

    # 使用 Qt 内存缓冲区编码图片，不创建临时文件。
    def _encode(self, pixmap: QPixmap, image_format: str, quality: int = -1) -> bytes:
        """将 QPixmap 写入内存并返回编码后的字节。"""
        data = QByteArray()
        buffer = QBuffer(data)
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            raise ScreenshotCaptureError("无法创建截图内存缓冲区。")
        try:
            if not pixmap.save(buffer, image_format, quality):
                raise ScreenshotCaptureError("截图编码失败。")
        finally:
            buffer.close()
        encoded = bytes(data)
        if not encoded:
            raise ScreenshotCaptureError("截图编码结果为空。")
        return encoded
