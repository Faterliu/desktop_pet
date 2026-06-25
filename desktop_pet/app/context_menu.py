from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu, QWidget


# 构建桌宠右键菜单，并绑定各项操作回调。
def build_context_menu(
    parent: QWidget,
    test_action_handler: Callable[[str], None],
    on_test_move_left: Callable[[], None],
    on_test_move_right: Callable[[], None],
    on_test_jump: Callable[[], None],
    on_test_proactive_speak: Callable[[], None],
    on_test_idle_prompt: Callable[[], None],
    on_test_api_proactive_speak: Callable[[], None],
    on_test_knowledge_speak: Callable[[], None],
    on_test_poetry: Callable[[], None],
    on_request_exit: Callable[[], None],
    current_scale: float,
    do_not_disturb: bool,
    auto_move: bool,
    api_chat_enabled: bool,
    formal_qa_mode: bool,
    formal_answer_display: str,
    always_on_top: bool,
    show_test_menu: bool,
    show_clear_menu: bool,
    show_reload_config: bool,
    on_set_scale: Callable[[float], None],
    on_custom_scale: Callable[[], None],
    on_toggle_dnd: Callable[[bool], None],
    on_toggle_auto_move: Callable[[bool], None],
    on_toggle_api_chat: Callable[[bool], None],
    on_toggle_formal_qa_mode: Callable[[bool], None],
    on_set_formal_answer_display: Callable[[str], None],
    on_toggle_always_on_top: Callable[[bool], None],
    on_reload_config: Callable[[], None],
    on_clear_informal_chat: Callable[[], None],
    on_clear_formal_chat: Callable[[], None],
) -> QMenu:
    """构建桌宠右键菜单，并绑定各项操作回调。"""
    menu = QMenu(parent)

    if show_test_menu:
        test_menu = menu.addMenu("测试")

        for action_name, title in [
            ("idle", "测试动作：idle"),
            ("waving", "测试动作：waving"),
            ("failed", "测试动作：failed"),
            ("review", "测试动作：review"),
            ("running", "测试动作：running"),
        ]:
            action = QAction(title, test_menu)
            action.triggered.connect(lambda checked=False, name=action_name: test_action_handler(name))
            test_menu.addAction(action)

        test_menu.addSeparator()

        move_left_action = QAction("测试左移", test_menu)
        move_left_action.triggered.connect(on_test_move_left)
        test_menu.addAction(move_left_action)

        move_right_action = QAction("测试右移", test_menu)
        move_right_action.triggered.connect(on_test_move_right)
        test_menu.addAction(move_right_action)

        jump_action = QAction("测试跳跃", test_menu)
        jump_action.triggered.connect(on_test_jump)
        test_menu.addAction(jump_action)

        test_menu.addSeparator()

        proactive_test_action = QAction("测试主动说话一次", test_menu)
        proactive_test_action.triggered.connect(on_test_proactive_speak)
        test_menu.addAction(proactive_test_action)

        api_proactive_test_action = QAction("测试 API 主动说话一次", test_menu)
        api_proactive_test_action.triggered.connect(on_test_api_proactive_speak)
        test_menu.addAction(api_proactive_test_action)

        idle_prompt_action = QAction("测试空闲问候逻辑", test_menu)
        idle_prompt_action.triggered.connect(on_test_idle_prompt)
        test_menu.addAction(idle_prompt_action)

        test_menu.addSeparator()

        knowledge_speak_action = QAction("测试主动问候知识内容", test_menu)
        knowledge_speak_action.triggered.connect(on_test_knowledge_speak)
        test_menu.addAction(knowledge_speak_action)

        test_menu.addSeparator()

        poetry_action = QAction("念一首诗", test_menu)
        poetry_action.triggered.connect(on_test_poetry)
        test_menu.addAction(poetry_action)

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

    formal_qa_action = QAction("正式问答模式", menu)
    formal_qa_action.setCheckable(True)
    formal_qa_action.setChecked(formal_qa_mode)
    formal_qa_action.toggled.connect(on_toggle_formal_qa_mode)
    menu.addAction(formal_qa_action)

    formal_display_menu = menu.addMenu("正式问答显示方式")
    formal_display_group = QActionGroup(formal_display_menu)
    formal_display_group.setExclusive(True)
    for mode, title in [
        ("new_panel", "每题新建文本框"),
        ("append", "追加到同一文本框"),
    ]:
        action = QAction(title, formal_display_menu)
        action.setCheckable(True)
        action.setChecked(formal_answer_display == mode)
        action.triggered.connect(
            lambda checked=False, value=mode: on_set_formal_answer_display(value)
        )
        formal_display_group.addAction(action)
        formal_display_menu.addAction(action)

    menu.addSeparator()

    top_action = QAction("窗口置顶", menu)
    top_action.setCheckable(True)
    top_action.setChecked(always_on_top)
    top_action.toggled.connect(on_toggle_always_on_top)
    menu.addAction(top_action)

    if show_clear_menu:
        menu.addSeparator()
        clear_informal_action = QAction("清除非正式聊天记录", menu)
        clear_informal_action.triggered.connect(on_clear_informal_chat)
        menu.addAction(clear_informal_action)

        clear_formal_action = QAction("清理正式问答记录", menu)
        clear_formal_action.triggered.connect(on_clear_formal_chat)
        menu.addAction(clear_formal_action)

    if show_reload_config:
        reload_action = QAction("重新加载配置", menu)
        reload_action.triggered.connect(on_reload_config)
        menu.addAction(reload_action)

    menu.addSeparator()
    exit_action = QAction("退出", menu)
    exit_action.triggered.connect(on_request_exit)
    menu.addAction(exit_action)
    return menu
