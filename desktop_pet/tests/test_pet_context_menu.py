from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from PySide6.QtCore import QEvent, QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QCursor, QKeyEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QFrame, QPushButton, QWidget  # noqa: E402

from app.bubble_position_service import BubblePositionService  # noqa: E402
from app.context_menu import (  # noqa: E402
    MenuAction,
    build_context_menu_actions,
    build_pet_context_menu,
)


class PetContextMenuTests(unittest.TestCase):
    # 初始化无界面测试所需的单例 QApplication。
    @classmethod
    def setUpClass(cls) -> None:
        """准备 Qt 应用对象，供悬浮菜单组件创建窗口。"""
        cls.app = QApplication.instance() or QApplication([])

    # 构造独立的动作模型，避免测试依赖旧 QMenu 构建器签名。
    def _menu_actions(self, **overrides: object) -> tuple[MenuAction, ...]:
        """构造当前卡片菜单所需的完整无副作用动作模型。"""
        values: dict[str, object] = {
            "test_action_handler": lambda action: None,
            "on_test_move_left": lambda: None,
            "on_test_move_right": lambda: None,
            "on_test_jump": lambda: None,
            "on_test_proactive_speak": lambda: None,
            "on_test_idle_prompt": lambda: None,
            "on_test_api_proactive_speak": lambda: None,
            "on_test_knowledge_speak": lambda: None,
            "on_test_poetry": lambda: None,
            "on_request_exit": lambda: None,
            "current_scale": 1.0,
            "do_not_disturb": False,
            "auto_move": False,
            "api_chat_enabled": False,
            "show_chat_api_menu": False,
            "api_provider": "openai",
            "formal_qa_mode": False,
            "formal_answer_display": "new_panel",
            "always_on_top": False,
            "show_test_menu": False,
            "show_clear_menu": False,
            "show_reload_config": False,
            "on_set_scale": lambda scale: None,
            "on_custom_scale": lambda: None,
            "on_toggle_dnd": lambda enabled: None,
            "on_toggle_auto_move": lambda enabled: None,
            "on_toggle_api_chat": lambda enabled: None,
            "on_set_api_provider": lambda provider: None,
            "on_toggle_formal_qa_mode": lambda enabled: None,
            "on_set_formal_answer_display": lambda mode: None,
            "on_toggle_always_on_top": lambda enabled: None,
            "on_reload_config": lambda: None,
            "on_clear_informal_chat": lambda: None,
            "on_clear_formal_chat": lambda: None,
            "on_add_ten_minute_reminder": lambda: None,
            "on_add_custom_minute_reminder": lambda: None,
            "on_view_current_reminders": lambda: None,
            "on_clear_completed_reminders": lambda: None,
            "on_clipboard_assistant": lambda mode: None,
            "on_screenshot_analysis": lambda mode: None,
        }
        values.update(overrides)
        return build_context_menu_actions(**values)  # type: ignore[arg-type]

    # 验证卡片显示在角色附近、不会与角色窗口重叠且不会越出当前屏幕。
    def test_card_is_positioned_near_pet_without_overlap(self) -> None:
        """验证环绕菜单复用屏幕安全定位服务。"""
        parent = QWidget()
        card = build_pet_context_menu(parent, character_name="小桃", actions=self._menu_actions())
        anchor = QRect(160, 160, 80, 80)
        positioner = BubblePositionService(QApplication)
        self.assertTrue(
            card.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        )
        surface = card.findChild(QWidget, "menu_surface")
        self.assertIsNotNone(surface)
        self.assertTrue(surface.testAttribute(Qt.WidgetAttribute.WA_StyledBackground))
        card.show_near(anchor, positioner, always_on_top=True)

        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        self.assertIsNotNone(screen)
        self.assertFalse(card.geometry().intersects(anchor))
        self.assertTrue(screen.availableGeometry().contains(card.geometry()))
        self.assertGreaterEqual(card.geometry().left(), anchor.right() + 12)
        self.assertEqual(card.width(), 280)
        self.assertEqual(
            card.button_for("剪贴板助手").width(),
            card.button_for("提醒").width(),
        )
        self.assertEqual(card.button_for("剪贴板助手").width(), 120)
        self.assertEqual(card.button_for("剪贴板助手").height(), 32)

        card.close()
        parent.close()

    # 验证常用功能保持一级，其余配置会被收纳到“设置”。
    def test_primary_actions_and_settings_grouping(self) -> None:
        """验证新的一级菜单分组不会遗漏原有配置入口。"""
        parent = QWidget()
        card = build_pet_context_menu(
            parent,
            character_name="小桃",
            actions=self._menu_actions(
                show_chat_api_menu=True,
                show_test_menu=True,
                show_clear_menu=True,
                show_reload_config=True,
            ),
        )
        for title in ("提醒", "剪贴板助手", "截图", "免打扰模式", "设置", "关闭菜单"):
            self.assertIsNotNone(card.button_for(title), title)
        self.assertIsNone(card.button_for("退出"))
        self.assertIsNone(card.button_for("人物缩放"))
        self.assertIsNone(card.button_for("正式问答模式"))
        self.assertEqual(card.grid.itemAtPosition(0, 0).widget().text(), "剪贴板助手")
        self.assertEqual(card.grid.itemAtPosition(1, 0).widget().text(), "截图")
        self.assertEqual(card.grid.itemAtPosition(1, 1).widget().text(), "免打扰模式")
        self.assertEqual(card.grid.itemAtPosition(2, 0).widget().objectName(), "menu_divider")
        self.assertIsNotNone(
            card.grid.itemAtPosition(2, 0).widget().findChild(QFrame, "menu_divider_line")
        )
        self.assertEqual(card.grid.itemAtPosition(3, 0).widget().text(), "设置")

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

    # 验证动作模型会按配置过滤可选入口，且不会重复定义动作标识。
    def test_action_model_filters_optional_entries_without_duplicate_ids(self) -> None:
        """验证条件菜单完全由模型控制，不依赖隐藏 QMenu 树。"""
        actions = self._menu_actions(
            show_chat_api_menu=False,
            show_test_menu=False,
            show_clear_menu=False,
            show_reload_config=False,
        )

        def flatten(entries: tuple[MenuAction, ...]) -> list[MenuAction]:
            result: list[MenuAction] = []
            for entry in entries:
                result.append(entry)
                result.extend(flatten(entry.children))
            return result

        all_actions = flatten(actions)
        action_ids = [action.action_id for action in all_actions]
        titles = [action.title for action in actions]
        self.assertEqual(len(action_ids), len(set(action_ids)))
        self.assertNotIn("聊天接入 API", titles)
        self.assertNotIn("测试", titles)
        self.assertNotIn("清除非正式聊天记录", titles)
        self.assertNotIn("重新加载配置", titles)

    # 验证设置菜单中的开关与互斥选项保留现有勾选语义。
    def test_settings_menu_preserves_toggle_and_exclusive_choice_state(self) -> None:
        """验证模型生成的 QAction 勾选状态和单选回调保持一致。"""
        selected_scales: list[float] = []
        parent = QWidget()
        card = build_pet_context_menu(
            parent,
            character_name="小桃",
            actions=self._menu_actions(
                current_scale=1.25,
                auto_move=True,
                on_set_scale=selected_scales.append,
            ),
        )
        settings_menu = card.submenu_for("设置")
        self.assertIsNotNone(settings_menu)
        settings_actions = {action.text(): action for action in settings_menu.actions()}
        self.assertTrue(settings_actions["自主移动"].isCheckable())
        self.assertTrue(settings_actions["自主移动"].isChecked())

        scale_menu = settings_actions["人物缩放"].menu()
        self.assertIsNotNone(scale_menu)
        scale_actions = {action.text(): action for action in scale_menu.actions()}
        self.assertTrue(scale_actions["1.25x"].isChecked())
        self.assertFalse(scale_actions["1.50x"].isChecked())
        scale_actions["1.50x"].trigger()
        self.assertEqual(selected_scales, [1.5])
        self.assertTrue(scale_actions["1.50x"].isChecked())
        self.assertFalse(scale_actions["1.25x"].isChecked())
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
            actions=self._menu_actions(on_toggle_dnd=toggles.append),
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
            actions=self._menu_actions(on_screenshot_analysis=modes.append),
        )
        screenshot_menu = card.submenu_for("截图")
        self.assertIsNotNone(screenshot_menu)
        self.assertTrue(
            screenshot_menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        )
        self.assertIn("border-radius: 10px", screenshot_menu.styleSheet())
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
        card = build_pet_context_menu(parent, character_name="小桃", actions=self._menu_actions())
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

    # 验证二级菜单关闭后不会让一级入口残留按下高亮。
    def test_submenu_close_resets_primary_button_highlight(self) -> None:
        """验证点击卡片空白处关闭二级菜单时一级按钮会复位。"""
        parent = QWidget()
        card = build_pet_context_menu(parent, character_name="小桃", actions=self._menu_actions())
        card.show_near(QRect(160, 160, 80, 80), BubblePositionService(QApplication), True)
        button = card.button_for("剪贴板助手")
        submenu = card.submenu_for("剪贴板助手")
        self.assertIsNotNone(button)
        self.assertIsNotNone(submenu)

        QTest.mouseMove(button, button.rect().center())
        button.click()
        self.app.processEvents()
        self.assertTrue(submenu.isVisible())
        self.assertTrue(button.isDown())
        self.assertTrue(button.underMouse())

        QCursor.setPos(card.mapToGlobal(QPoint(2, 2)))
        submenu.hide()
        self.app.processEvents()
        self.assertFalse(button.isDown())
        self.assertFalse(button.underMouse())
        parent.close()

    # 验证 Esc 可关闭卡片，免打扰以外的普通动作不受影响。
    def test_escape_closes_card(self) -> None:
        """验证键盘关闭路径不会保留悬浮卡片。"""
        parent = QWidget()
        card = build_pet_context_menu(parent, character_name="小桃", actions=self._menu_actions())
        card.show_near(QRect(160, 160, 80, 80), BubblePositionService(QApplication), True)
        card.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self.assertFalse(card.isVisible())
        parent.close()

    # 验证底部关闭菜单按钮只关闭卡片，不触发退出程序。
    def test_bottom_close_button_closes_card(self) -> None:
        """验证“关闭菜单”按钮可安全收起当前菜单卡片。"""
        parent = QWidget()
        card = build_pet_context_menu(parent, character_name="小桃", actions=self._menu_actions())
        card.show_near(QRect(160, 160, 80, 80), BubblePositionService(QApplication), True)
        close_button = card.button_for("关闭菜单")
        self.assertIsNotNone(close_button)

        close_button.click()
        self.assertFalse(card.isVisible())
        parent.close()

    # 验证标题右上角符号会触发既有退出程序回调。
    def test_header_exit_button_triggers_program_exit(self) -> None:
        """验证“×”不再只是关闭菜单，而是请求退出桌宠。"""
        parent = QWidget()
        exit_requests: list[bool] = []
        card = build_pet_context_menu(
            parent,
            character_name="小桃",
            actions=self._menu_actions(on_request_exit=lambda: exit_requests.append(True)),
        )
        card.show_near(QRect(160, 160, 80, 80), BubblePositionService(QApplication), True)
        exit_button = card.findChild(QPushButton, "menu_exit")
        self.assertIsNotNone(exit_button)
        self.assertEqual(exit_button.text(), "退出程序")
        self.assertEqual(exit_button.size().width(), 52)
        self.assertEqual(exit_button.size().height(), 18)

        exit_button.click()
        self.assertEqual(exit_requests, [True])
        self.assertFalse(card.isVisible())
        parent.close()


if __name__ == "__main__":
    unittest.main()
