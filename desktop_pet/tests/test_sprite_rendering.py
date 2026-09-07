from __future__ import annotations

import sys
import unittest
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QLabel, QWidget

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from animation.sprite_player import SpritePlayer
from utils.sprite_mask import visible_sprite_mask


class SpriteRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """共享离屏应用，测试不启动宠物业务和后台任务。"""
        cls.app = QApplication.instance() or QApplication([])

    def test_mask_preserves_every_nonzero_alpha_and_row_padding(self) -> None:
        """跨越字节边界的弱透明细边必须保留，全透明背景仍可穿透。"""
        image = QImage(37, 3, QImage.Format.Format_RGBA8888)
        image.fill(Qt.GlobalColor.transparent)
        samples = [(0, 0, 1), (7, 0, 64), (8, 1, 127), (31, 1, 128), (36, 2, 255)]
        for x, y, alpha in samples:
            image.setPixelColor(x, y, QColor(40, 30, 20, alpha))
        region = QRegion(visible_sprite_mask(QPixmap.fromImage(image)))
        expected = {(x, y) for x, y, _ in samples}
        for y in range(3):
            for x in range(37):
                self.assertEqual(region.contains(QPoint(x, y)), (x, y) in expected)

    def test_fractional_scale_keeps_thin_line_at_every_source_position(self) -> None:
        """缩小后的一像素竖线不应随源像素位置变化而整条消失。"""
        player = SpritePlayer(ROOT / "assets" / "sprite_config.json", scale=0.6)
        player.timer.stop()
        try:
            for x in range(3, 16):
                image = QImage(20, 20, QImage.Format.Format_RGBA8888)
                image.fill(Qt.GlobalColor.transparent)
                for y in range(2, 18):
                    image.setPixelColor(x, y, QColor(30, 20, 10, 255))
                player.frames_by_action = {"idle": [QPixmap.fromImage(image)]}
                player.current_action = "idle"
                player.current_index = 0
                scaled = player.current_pixmap()
                result = scaled.toImage()
                alphas = [result.pixelColor(col, 5).alpha() for col in range(result.width())]
                self.assertGreater(sum(alphas), 0, f"源列 {x} 的细线消失")
                self.assertTrue(any(0 < value < 255 for value in alphas))
                region = QRegion(visible_sprite_mask(scaled))
                for col, alpha in enumerate(alphas):
                    self.assertEqual(region.contains(QPoint(col, 5)), alpha > 0)
        finally:
            player.timer.stop()

    def test_integer_enlargement_preserves_pixel_edges(self) -> None:
        """整数倍放大仍保持像素边界，不引入半透明模糊。"""
        player = SpritePlayer(ROOT / "assets" / "sprite_config.json", scale=2.0)
        player.timer.stop()
        try:
            result = player.current_pixmap().toImage()
            self.assertEqual((result.width(), result.height()), (384, 416))
            self.assertTrue(all(result.pixelColor(x, y).alpha() in (0, 255)
                                for y in range(result.height()) for x in range(result.width())))
        finally:
            player.timer.stop()

    def test_window_mask_does_not_clip_faint_edge_twice(self) -> None:
        """窗口更新必须保留弱透明像素，并清除标签上遗留的二次裁剪。"""
        from app.desktop_pet_window import DesktopPetWindow

        window = QWidget()
        window.sprite_label = QLabel(window)
        image = QImage(4, 4, QImage.Format.Format_RGBA8888)
        image.fill(Qt.GlobalColor.transparent)
        image.setPixelColor(1, 1, QColor(20, 20, 20, 255))
        image.setPixelColor(2, 1, QColor(20, 20, 20, 20))
        pixmap = QPixmap.fromImage(image)
        window.sprite_label.setMask(pixmap.mask())
        try:
            DesktopPetWindow._apply_sprite_window_mask(window, pixmap)
            self.assertTrue(window.mask().contains(QPoint(2, 1)))
            self.assertFalse(window.mask().contains(QPoint(3, 1)))
            self.assertTrue(window.sprite_label.mask().isEmpty())
            DesktopPetWindow._apply_sprite_window_mask(window, QPixmap())
            self.assertTrue(window.mask().isEmpty())
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
