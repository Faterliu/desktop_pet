from __future__ import annotations

import sys
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from animation.sprite_player import DEFAULT_SPRITE_CONFIG, SpritePlayer  # noqa: E402


class SpritePlayerLoadingTests(unittest.TestCase):
    # 验证默认配置也包含新图集中的三个新增动作，配置损坏时仍可正常恢复。
    def test_default_config_includes_new_actions(self) -> None:
        """验证默认配置包含新增动作。"""
        actions = DEFAULT_SPRITE_CONFIG["actions"]

        self.assertEqual(actions["happy"]["row"], 9)
        self.assertEqual(actions["sleepy"]["row"], 10)
        self.assertEqual(actions["leaf-hug"]["row"], 11)

    # 验证实际精灵图集会裁切新动作，并能切换到对应动作而不回退 idle。
    def test_new_actions_are_loaded_and_selectable(self) -> None:
        """验证新增动作被加载并可切换。"""
        app = QApplication.instance() or QApplication([])
        player = SpritePlayer(DESKTOP_PET_ROOT / "assets" / "sprite_config.json", scale=0.9)
        try:
            for action_name in ("happy", "sleepy", "leaf-hug"):
                with self.subTest(action_name=action_name):
                    self.assertIn(action_name, player.frames_by_action)
                self.assertEqual(len(player.frames_by_action[action_name]), 16)
                player.set_action(action_name)
                self.assertEqual(player.current_action, action_name)
                self.assertEqual(player.current_pixmap().size().width(), 172)
                self.assertEqual(player.current_pixmap().size().height(), 187)
        finally:
            player.timer.stop()
            del app


if __name__ == "__main__":
    unittest.main()
