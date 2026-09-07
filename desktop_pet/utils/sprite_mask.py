"""保留精灵半透明边缘的窗口裁剪掩码。"""

from PySide6.QtGui import QBitmap, QImage, QPixmap, qRgb


def visible_sprite_mask(pixmap: QPixmap) -> QBitmap:
    """仅裁掉完全透明像素，避免二值透明度阈值吞掉缩放后的细线。"""
    if pixmap.isNull():
        return QBitmap()
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    width, height = image.width(), image.height()
    source = image.constBits()
    source_stride = image.bytesPerLine()
    mask_stride = ((width + 31) // 32) * 4
    pixels = bytearray(mask_stride * height)
    for y in range(height):
        for x in range(width):
            if source[y * source_stride + x * 4 + 3] > 0:
                pixels[y * mask_stride + x // 8] |= 0x80 >> (x % 8)
    mask_image = QImage(bytes(pixels), width, height, mask_stride, QImage.Format.Format_Mono)
    mask_image.setColorTable([qRgb(255, 255, 255), qRgb(0, 0, 0)])
    return QBitmap.fromImage(mask_image)
