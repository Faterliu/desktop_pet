from __future__ import annotations

import inspect
import os
import sys
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from PySide6.QtCore import QEvent, QRect, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton, QWidget  # noqa: E402

from app.bubble_position_service import BubblePositionService  # noqa: E402
from app.context_menu import build_context_menu, build_pet_context_menu  # noqa: E402


class PetContextMenuTests(unittest.TestCase):
    # 初始化无界面测试所需的单例 QApplication。
    @classmethod
    def setUpClass(cls) -> None:
        """准备 Qt 应用对象，供悬浮菜单组件创建窗口。"""
        cls.app = QApplication.instance() or QApplication([])

    # 按既有菜单构造函数签名生成完整的无副作用回调参数。
    def _menu_kwargs(self, **overrides: object) -> dict[str, object]:
        """构造旧菜单与卡片菜单共用的最小测试参数。"""
        callbacks: dict[str, object] = {}
        bool_names = {
            "do_not_disturb",
            "auto_move",
            "api_chat_enabled",
            "show_chat_api_menu",
            "formal_qa_mode",
            "always_on_top",
            "show_test_menu",
            "show_clear_menu",
            "show_reload_config",
        }
        for name in inspect.signature(build_context_menu).parameters:
            if name == "parent":
                continue
            if name == "current_scale":
                callbacks[name] = 1.0
            elif name in bool_names:
                callbacks[name] = False
            elif name == "api_provider":
                callbacks[name] = "openai"
            elif name == "formal_answer_display":
                callbacks[name] = "new_panel"
            else:
                callbacks[name] = lambda *args, **kwargs: None
        callbacks.update(overrides)
        return callbacks

    # 验证卡片显示在角色附近、不会与角色窗口重叠且不会越出当前屏幕。
    def test_card_is_positioned_near_pet_without_overlap(self) -> None:
        """验证环绕菜单复用屏幕安全定位服务。"""
        parent = QWidget()
        card = build_pet_context_menu(parent, character_name="小桃", **self._menu_kwargs())
        anchor = QRect(160, 160, 80, 80)
        positioner = BubblePositionService(QApplication)
        card.show_near(anchor, positioner, always_on_top=True)

        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        self.assertIsNotNone(screen)
        self.assertFalse(card.geometry().intersects(anchor))
        self.assertTrue(screen.availableGeometry().contains(card.geometry()))
        self.assertGreaterEqual(card.geometry().left(), anchor.right() + 12)

        card.close()
        parent.close()

    # 验证常用功能保持一级，其余配置会被收纳到“设置”。
    def test_primary_actions_and_settings_grouping(self) -> None:
        """验证新的一级菜单分组不会遗漏原有配置入口。"""
        parent = QWidget()
        card = build_pet_context_menu(
            parent,
            character_name="小桃",
            **self._menu_kwargs(
                show_chat_api_menu=True,
                show_test_menu=True,
                show_clear_menu=True,
                show_reload_config=True,
            ),
        )
        for title in ("提醒", "剪贴板助手", "截图", "免打扰模式", "设置", "退出"):
            self.assertIsNotNone(card.button_for(title), title)
        self.assertIsNone(card.button_for("人物缩放"))
        self.assertIsNone(card.button_for("正式问答模式"))
        self.assertEqual(card.grid.itemAtPosition(0, 0).widget().text(), "剪贴板助手  ›")
        self.assertEqual(card.grid.itemAtPosition(1, 0).widget().text(), "免打扰模式")

        settings_menu = card.submenu_for("设置")
        self.assertIsNotNone(settings_menu)
        setting_titles = {action.text() for action in settings_menu.actions()}
        self.assertTrue(
            {
                "测试",
                "人物缩放",
                "自主移动",
                "聊天接入 API",
                "正式问答模式",
                "正式问答显示方式",
                "窗口置顶",
                "重新加载配置",
            }.issubset(setting_titles)
        )
        card.close()
        parent.close()

    # 验证开关按钮显示勾选状态并继续触发原有 QAction 回调。
    def test_toggle_button_preserves_checked_state_and_callback(self) -> None:
        """验证一级卡片没有改变既有免打扰动作语义。"""
        parent = QWidget()
        toggles: list[bool] = []
        card = build_pet_context_menu(
            parent,
            character_name="小桃",
            **self._menu_kwargs(on_toggle_dnd=toggles.append),
        )
        button = card.button_for("免打扰模式")
        self.assertIsInstance(button, QPushButton)
        self.assertFalse(button.isChecked())

        button.click()
        self.assertEqual(toggles, [True])
        parent.close()

    # 验证二级截图入口和既有模式回调仍然完整保留。
    def test_screenshot_submenu_keeps_both_modes(self) -> None:
        """验证微型卡片仍可复用截图二级菜单的两种操作。"""
        parent = QWidget()
        modes: list[str] = []
        card = build_pet_context_menu(
            parent,
            character_name="小桃",
            **self._menu_kwargs(on_screenshot_analysis=modes.append),
        )
        screenshot_menu = card.submenu_for("截图")
        self.assertIsNotNone(screenshot_menu)
        actions = {action.text(): action for action in screenshot_menu.actions()}
        actions["全屏快速解析"].trigger()
        actions["框选截图并提问"].trigger()

        self.assertEqual(modes, ["full", "region_question"])
        card.close()
        parent.close()

    # 验证可见卡片点击二级入口后能弹出菜单，并在选择后记录一次互动。
    def test_submenu_button_opens_menu_and_records_interaction(self) -> None:
        """验证二级菜单不因一级卡片的 Popup 生命周期提前关闭。"""
        parent = QWidget()
        card = build_pet_context_menu(parent, character_name="小桃", **self._menu_kwargs())
        interactions: list[bool] = []
        card.interacted.connect(lambda: interactions.append(True))
        card.show_near(QRect(160, 160, 80, 80), BubblePositionService(QApplication), True)

        button = card.button_for("截图")
        self.assertIsNotNone(button)
        button.click()
        self.app.processEvents()
        screenshot_menu = card.submenu_for("截图")
        self.assertIsNotNone(screenshot_menu)
        self.assertTrue(screenshot_menu.isVisible())

        screenshot_menu.actions()[0].trigger()
        self.assertEqual(interactions, [True])
        parent.close()

    # 验证 Esc 可关闭卡片，免打扰以外的普通动作不受影响。
    def test_escape_closes_card(self) -> None:
        """验证键盘关闭路径不会保留悬浮卡片。"""
        parent = QWidget()
        card = build_pet_context_menu(parent, character_name="小桃", **self._menu_kwargs())
        card.show_near(QRect(160, 160, 80, 80), BubblePositionService(QApplication), True)
        card.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self.assertFalse(card.isVisible())
        parent.close()


if __name__ == "__main__":
    unittest.main()
