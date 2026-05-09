from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu, QWidget


def build_context_menu(
    parent: QWidget,
    test_action_handler: Callable[[str], None],
    current_scale: float,
    do_not_disturb: bool,
    auto_move: bool,
    api_chat_enabled: bool,
    on_set_scale: Callable[[float], None],
    on_custom_scale: Callable[[], None],
    on_toggle_dnd: Callable[[bool], None],
    on_toggle_auto_move: Callable[[bool], None],
    on_toggle_api_chat: Callable[[bool], None],
    on_clear_history: Callable[[], None],
    on_reload_config: Callable[[], None],
) -> QMenu:
    """构建桌宠右键菜单，并绑定各项操作回调。"""
    menu = QMenu(parent)
    for action_name, title in [
        ("idle", "测试动作：idle"),
        ("waving", "测试动作：waving"),
        ("failed", "测试动作：failed"),
        ("review", "测试动作：review"),
        ("running", "测试动作：running"),
    ]:
        action = QAction(title, menu)
        action.triggered.connect(lambda checked=False, name=action_name: test_action_handler(name))
        menu.addAction(action)

    menu.addSeparator()

    scale_menu = menu.addMenu("人物缩放")
    scale_group = QActionGroup(scale_menu)
    scale_group.setExclusive(True)
    for scale in [0.75, 1.0, 1.25, 1.5, 2.0]:
        action = QAction(f"{scale:.2f}x", scale_menu)
        action.setCheckable(True)
        action.setChecked(abs(current_scale - scale) < 0.001)
        action.triggered.connect(lambda checked=False, value=scale: on_set_scale(value))
        scale_group.addAction(action)
        scale_menu.addAction(action)
    scale_menu.addSeparator()
    custom_scale_action = QAction("自定义缩放...", scale_menu)
    custom_scale_action.triggered.connect(on_custom_scale)
    scale_menu.addAction(custom_scale_action)

    menu.addSeparator()

    dnd_action = QAction("免打扰模式", menu)
    dnd_action.setCheckable(True)
    dnd_action.setChecked(do_not_disturb)
    dnd_action.toggled.connect(on_toggle_dnd)
    menu.addAction(dnd_action)

    move_action = QAction("自主移动", menu)
    move_action.setCheckable(True)
    move_action.setChecked(auto_move)
    move_action.toggled.connect(on_toggle_auto_move)
    menu.addAction(move_action)

    api_action = QAction("聊天接入 API", menu)
    api_action.setCheckable(True)
    api_action.setChecked(api_chat_enabled)
    api_action.toggled.connect(on_toggle_api_chat)
    menu.addAction(api_action)

    menu.addSeparator()

    clear_action = QAction("清空聊天记录", menu)
    clear_action.triggered.connect(on_clear_history)
    menu.addAction(clear_action)

    reload_action = QAction("重新加载配置", menu)
    reload_action.triggered.connect(on_reload_config)
    menu.addAction(reload_action)

    menu.addSeparator()
    menu.addAction("退出", parent.close)
    return menu
