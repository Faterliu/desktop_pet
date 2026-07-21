from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QKeyEvent, QPainter
from PySide6.QtWidgets import (
    QGridLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


MENU_STYLE = """
QMenu {
    background: #f7f2ea;
    border: 1px solid #d9c6af;
    border-radius: 10px;
    padding: 4px;
    color: #5a4331;
    font-size: 11px;
}
QMenu::item {
    background: #f8f4ed;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 5px 20px 5px 8px;
    margin: 0 1px;
}
QMenu::item:selected { background: #fff0dc; border-color: #d7a164; }
QMenu::item:checked { background: #f8e3c6; border-color: #c88e4c; }
QMenu::separator { height: 1px; background: #e4d6c7; margin: 4px 5px; }
"""


class MenuSubmenuButton(QToolButton):
    """在右侧绘制固定箭头的二级菜单按钮。"""

    # 在默认按钮内容之上绘制固定位置的二级箭头。
    def paintEvent(self, event: object) -> None:  # noqa: N802
        """保持文字左对齐，并把箭头稳定放在按钮右侧。"""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = painter.font()
        font.setPixelSize(10)
        painter.setFont(font)
        painter.setPen(QColor("#a77a52"))
        painter.drawText(
            QRect(self.width() - 23, 0, 11, self.height()),
            Qt.AlignmentFlag.AlignCenter,
            "›",
        )
        painter.end()


class DndToggleButton(QPushButton):
    """带右侧开关指示器的免打扰模式按钮。"""

    # 在默认按钮内容之上绘制免打扰模式的开关状态。
    def paintEvent(self, event: object) -> None:  # noqa: N802
        """用柔和颜色显示开关当前是否开启。"""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRect(self.width() - 37, (self.height() - 16) // 2, 26, 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e7b26b") if self.isChecked() else QColor("#d8cec2"))
        painter.drawRoundedRect(track, 8, 8)
        knob_x = track.right() - 9 if self.isChecked() else track.left() + 2
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(knob_x, track.top() + 3, 10, 10)
        painter.end()


class PetContextMenu(QWidget):
    """显示在桌宠附近的双列微型右键菜单卡片。"""

    interacted = Signal()

    # 初始化菜单卡片布局、标题与基础视觉样式。
    def __init__(self, parent: QWidget, character_name: str, legacy_menu: QMenu) -> None:
        """初始化菜单卡片，并持有旧菜单作为二级功能来源。"""
        super().__init__(
            parent,
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setFixedWidth(280)
        self.setStyleSheet(
            """
            PetContextMenu {
                background: transparent;
                border: none;
            }
            QWidget#menu_surface {
                background: #f7f2ea;
                border: 1px solid #d9c6af;
                border-radius: 9px;
            }
            QLabel#menu_title {
                background: transparent;
                border: none;
                color: #4e3a2a;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton#menu_exit {
                background: #f6efef;
                border: none;
                border-radius: 5px;
                color: #c86a6a;
                font-size: 10px;
                font-weight: 600;
                padding: 0 4px;
            }
            QPushButton#menu_exit:hover {
                background: #fbe8e8;
                color: #a95050;
            }
            QPushButton#menu_button, QToolButton#menu_button {
                background: #f8f4ed;
                border: 1px solid #ddb98c;
                border-radius: 9px;
                color: #5a4331;
                font-size: 11px;
                font-weight: 500;
                padding: 4px 11px;
                text-align: left;
            }
            QToolButton#menu_button[submenu="true"] { padding-right: 30px; }
            QPushButton#menu_button[dnd_toggle="true"] { padding-right: 44px; }
            QPushButton#menu_button:hover, QToolButton#menu_button:hover {
                background: #fff0dc;
                border-color: #d7a164;
                color: #5a4331;
            }
            QPushButton#menu_button:pressed, QToolButton#menu_button:pressed {
                background: #f8e3c6;
                border-color: #c88e4c;
                color: #5a4331;
            }
            QPushButton#menu_button:checked {
                background: #fff0dc;
                border-color: #d7a164;
                color: #5a4331;
            }
            QPushButton#menu_button[danger="true"] {
                background: #f6efef;
                border-color: #e2b7b7;
                color: #c86a6a;
            }
            QPushButton#menu_button[danger="true"]:hover {
                background: #fbe8e8;
                border-color: #d99898;
            }
            QWidget#menu_divider {
                background: transparent;
                border: none;
            }
            QFrame#menu_divider_line {
                background: #e4d6c7;
                border: none;
                max-height: 1px;
            }
            """
        )
        self._legacy_menu = legacy_menu
        self.destroyed.connect(self._legacy_menu.deleteLater)
        self._buttons: dict[str, QPushButton | QToolButton] = {}
        self._submenu_actions: dict[str, QAction] = {}
        self._settings_menu: QMenu | None = None
        self._exit_action: QAction | None = None
        self._always_on_top: bool | None = None
        self._legacy_menu.triggered.connect(self._complete_submenu_action)

        frame_layout = QVBoxLayout(self)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)
        surface = QWidget(self)
        surface.setObjectName("menu_surface")
        surface.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        frame_layout.addWidget(surface)

        root = QVBoxLayout(surface)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(7)
        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 0, 0)
        title = QLabel(f"{character_name}的小菜单", self)
        title.setObjectName("menu_title")
        header.addWidget(title)
        header.addStretch(1)
        close_button = QPushButton("退出程序", self)
        close_button.setObjectName("menu_exit")
        close_button.setFixedSize(52, 18)
        close_button.setToolTip("退出程序")
        close_button.clicked.connect(self._request_exit)
        header.addWidget(close_button)
        root.addLayout(header)

        self.grid = QGridLayout()
        self.grid.setContentsMargins(6, 0, 6, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(6)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)
        root.addLayout(self.grid)
        self._grid_row = 0
        self._grid_column = 0
        self._button_width = 120
        self._add_legacy_actions()

    # 按人物窗口和定位服务显示菜单卡片。
    def show_near(self, anchor_rect: QRect, position_service: object, always_on_top: bool) -> None:
        """把菜单显示在人物周围合适的位置，并同步置顶设置。"""
        self._set_always_on_top(always_on_top)
        self.adjustSize()
        self.reposition(anchor_rect, position_service)
        self.show()
        self.raise_()
        self.activateWindow()

    # 在人物移动后重新选择附近的安全位置。
    def reposition(self, anchor_rect: QRect, position_service: object) -> None:
        """调用既有气泡定位服务，使菜单避开人物和屏幕边缘。"""
        positioner = getattr(position_service, "context_menu_position", None)
        if not callable(positioner):
            positioner = getattr(position_service, "speech_bubble_position", None)
        if not callable(positioner):
            return
        position = positioner((self.width(), self.height()), anchor_rect)
        if isinstance(position, QPoint):
            self.move(position)

    # 返回指定标题的按钮，供测试和局部状态验证使用。
    def button_for(self, title: str) -> QPushButton | QToolButton | None:
        """返回指定一级菜单按钮，不存在时返回空值。"""
        return self._buttons.get(title)

    # 返回指定标题对应的二级菜单，供测试和回归验证使用。
    def submenu_for(self, title: str) -> QMenu | None:
        """返回指定二级菜单，不存在时返回空值。"""
        action = self._submenu_actions.get(title)
        return action.menu() if action is not None else None

    # 处理 Esc 关闭，其他按键保持 Qt 默认行为。
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        """按下 Esc 时关闭悬浮菜单卡片。"""
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)

    # 将旧一级菜单动作映射为卡片按钮，二级菜单继续复用 QMenu。
    def _add_legacy_actions(self) -> None:
        """把常用入口放在一级，其余设置动作收纳到二级菜单。"""
        primary_titles = {"提醒", "剪贴板助手", "截图", "免打扰模式"}
        primary_actions: dict[str, QAction] = {}
        settings_actions: list[QAction] = []
        for action in self._legacy_menu.actions():
            if action.isSeparator():
                continue
            title = action.text()
            if title == "退出":
                continue
            if title not in primary_titles:
                settings_actions.append(action)
                continue
            primary_actions[title] = action

        for title in ("剪贴板助手", "提醒", "截图", "免打扰模式"):
            action = primary_actions.get(title)
            if action is not None:
                self._add_legacy_entry(title, action)

        self._add_divider()
        self._add_settings_menu(settings_actions)
        exit_action = next(
            (action for action in self._legacy_menu.actions() if action.text() == "退出"),
            None,
        )
        if exit_action is not None:
            self._exit_action = exit_action
        self._add_close_menu_button()

    # 按动作类型添加一个一级卡片入口。
    def _add_legacy_entry(self, title: str, action: QAction) -> None:
        """把一个既有动作转换为普通按钮、开关或二级入口。"""
        submenu = action.menu()
        if submenu is not None:
            self._add_submenu(title, action)
            return
        if action.isCheckable():
            self._add_toggle(title, action)
            return
        self._add_action(title, action, danger=False)

    # 收纳非高频配置动作，避免一级卡片内容过多。
    def _add_settings_menu(self, actions: list[QAction]) -> None:
        """创建“设置”二级菜单，并保留每个既有 QAction 的回调。"""
        if not actions:
            return
        settings_menu = QMenu("设置", self._legacy_menu)
        for action in actions:
            settings_menu.addAction(action)
        settings_menu.triggered.connect(self._complete_submenu_action)
        self._settings_menu = settings_menu
        self._add_submenu("设置", settings_menu.menuAction())

    # 添加执行旧 QAction 的普通卡片按钮。
    def _add_action(self, title: str, action: QAction, *, danger: bool) -> None:
        """添加普通按钮，并在点击时触发原有 QAction 回调。"""
        button = self._new_button(title)
        if danger:
            button.setProperty("danger", "true")
            button.style().unpolish(button)
            button.style().polish(button)
        button.clicked.connect(lambda checked=False, target=action: self._trigger_action(target))
        self._add_button(title, button)

    # 添加只关闭当前卡片的底部按钮，避免与退出程序混淆。
    def _add_close_menu_button(self) -> None:
        """添加“关闭菜单”按钮，不触发桌宠退出流程。"""
        button = self._new_button("关闭菜单")
        button.clicked.connect(self._close_menu)
        self._add_button("关闭菜单", button)

    # 添加能显示勾选状态的旧 QAction 开关按钮。
    def _add_toggle(self, title: str, action: QAction) -> None:
        """添加带固定位置状态开关的按钮，并保持原 QAction 状态一致。"""
        button = DndToggleButton(title, self)
        button.setObjectName("menu_button")
        button.setProperty("dnd_toggle", "true")
        button.setFixedHeight(32)
        button.setFixedWidth(self._button_width)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        button.setCheckable(True)
        button.setChecked(action.isChecked())
        button.clicked.connect(
            lambda enabled=False, target=action: self._trigger_action(target)
        )
        self._add_button(title, button)

    # 添加打开原有二级 QMenu 的卡片入口。
    def _add_submenu(self, title: str, action: QAction) -> None:
        """添加二级菜单入口，并为其套用统一的轻量菜单样式。"""
        submenu = action.menu()
        if submenu is None:
            return
        self._style_menu_tree(submenu)
        button = MenuSubmenuButton(self)
        button.setObjectName("menu_button")
        button.setProperty("class", "menu_button")
        button.setProperty("submenu", "true")
        button.setText(title)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setFixedHeight(32)
        button.setFixedWidth(self._button_width)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        button.clicked.connect(
            lambda checked=False, target=button, target_action=action: self._show_submenu(
                target,
                target_action,
            )
        )
        self._submenu_actions[title] = action
        self._add_button(title, button)

    # 在卡片按钮旁弹出原有二级菜单，避免转移 QMenu 的所有权。
    def _show_submenu(self, button: QToolButton, action: QAction) -> None:
        """显示二级菜单，并让 Qt 自动处理屏幕边缘位置。"""
        submenu = action.menu()
        if submenu is None:
            return
        self._style_menu_tree(submenu)
        submenu.popup(button.mapToGlobal(QPoint(button.width() - 8, 0)))

    # 创建统一尺寸和属性的一级普通按钮。
    def _new_button(self, title: str) -> QPushButton:
        """创建用于一级菜单的圆角按钮。"""
        button = QPushButton(title, self)
        button.setObjectName("menu_button")
        button.setProperty("class", "menu_button")
        button.setFixedHeight(32)
        button.setFixedWidth(self._button_width)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return button

    # 将按钮顺序填充到双列网格。
    def _add_button(self, title: str, button: QPushButton | QToolButton) -> None:
        """把新按钮按当前数量插入双列卡片网格。"""
        self.grid.addWidget(button, self._grid_row, self._grid_column)
        self._grid_column += 1
        if self._grid_column == 2:
            self._grid_column = 0
            self._grid_row += 1
        self._buttons[title] = button

    # 在高频功能与系统设置之间加入轻量分隔。
    def _add_divider(self) -> None:
        """添加跨两列的细分隔线，建立底部操作层级。"""
        if self._grid_column:
            self._grid_column = 0
            self._grid_row += 1
        divider = QWidget(self)
        divider.setObjectName("menu_divider")
        divider.setFixedHeight(5)
        divider_layout = QVBoxLayout(divider)
        divider_layout.setContentsMargins(0, 2, 0, 2)
        divider_layout.setSpacing(0)
        divider_line = QFrame(divider)
        divider_line.setObjectName("menu_divider_line")
        divider_line.setFrameShape(QFrame.Shape.HLine)
        divider_layout.addWidget(divider_line)
        self.grid.addWidget(divider, self._grid_row, 0, 1, 2)
        self._grid_row += 1

    # 执行旧 QAction 并关闭卡片。
    def _trigger_action(self, action: QAction) -> None:
        """通知互动、关闭菜单，再触发原有动作。"""
        self.interacted.emit()
        self.close()
        action.trigger()

    # 关闭当前菜单，并把它视作一次有效用户交互。
    def _close_menu(self) -> None:
        """关闭菜单卡片，不退出桌宠程序。"""
        self.interacted.emit()
        self.close()

    # 由标题栏关闭符号触发既有的程序退出动作。
    def _request_exit(self) -> None:
        """触发退出程序动作；构建期间缺失动作时安全忽略。"""
        if self._exit_action is not None:
            self._trigger_action(self._exit_action)

    # 二级菜单动作触发后关闭一级卡片并记录互动。
    def _complete_submenu_action(self, action: QAction) -> None:
        """在二级菜单选择叶子动作后完成一级菜单交互。"""
        if action.isSeparator() or not self.isVisible():
            return
        self.interacted.emit()
        self.close()

    # 为当前二级菜单及其嵌套菜单应用奶油色列表样式。
    def _style_menu_tree(self, menu: QMenu) -> None:
        """递归设置二级菜单样式，保持一级与二级视觉一致。"""
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        menu.setStyleSheet(MENU_STYLE)
        for child_menu in menu.findChildren(QMenu):
            child_menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            child_menu.setStyleSheet(MENU_STYLE)

    # 按窗口置顶配置更新弹窗标志。
    def _set_always_on_top(self, enabled: bool) -> None:
        """让菜单卡片与桌宠窗口保持相同的置顶策略。"""
        if self._always_on_top == enabled:
            return
        self._always_on_top = enabled
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)


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
    show_chat_api_menu: bool,
    api_provider: str,
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
    on_set_api_provider: Callable[[str], None],
    on_toggle_formal_qa_mode: Callable[[bool], None],
    on_set_formal_answer_display: Callable[[str], None],
    on_toggle_always_on_top: Callable[[bool], None],
    on_reload_config: Callable[[], None],
    on_clear_informal_chat: Callable[[], None],
    on_clear_formal_chat: Callable[[], None],
    on_add_ten_minute_reminder: Callable[[], None],
    on_add_custom_minute_reminder: Callable[[], None],
    on_view_current_reminders: Callable[[], None],
    on_clear_completed_reminders: Callable[[], None],
    on_clipboard_assistant: Callable[[str], None],
    on_screenshot_analysis: Callable[[str], None],
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

        test_menu.addSeparator()

        provider_menu = test_menu.addMenu("测试模型切换")
        provider_group = QActionGroup(provider_menu)
        provider_group.setExclusive(True)
        for provider, title in [("deepseek", "DeepSeek"), ("openai", "OpenAI GPT")]:
            action = QAction(title, provider_menu)
            action.setCheckable(True)
            action.setChecked(api_provider == provider)
            action.triggered.connect(
                lambda checked=False, value=provider: on_set_api_provider(value)
            )
            provider_group.addAction(action)
            provider_menu.addAction(action)

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

    if show_chat_api_menu:
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

    reminder_menu = menu.addMenu("提醒")
    ten_minute_reminder_action = QAction("添加 10 分钟后提醒...", reminder_menu)
    ten_minute_reminder_action.triggered.connect(on_add_ten_minute_reminder)
    reminder_menu.addAction(ten_minute_reminder_action)

    custom_reminder_action = QAction("添加自定义分钟提醒...", reminder_menu)
    custom_reminder_action.triggered.connect(on_add_custom_minute_reminder)
    reminder_menu.addAction(custom_reminder_action)

    reminder_menu.addSeparator()
    view_reminders_action = QAction("查看当前提醒", reminder_menu)
    view_reminders_action.triggered.connect(on_view_current_reminders)
    reminder_menu.addAction(view_reminders_action)

    clear_completed_reminders_action = QAction("清空已完成提醒", reminder_menu)
    clear_completed_reminders_action.triggered.connect(on_clear_completed_reminders)
    reminder_menu.addAction(clear_completed_reminders_action)

    clipboard_menu = menu.addMenu("剪贴板助手")
    for mode, title in [
        ("summarize", "总结剪贴板"),
        ("translate", "翻译剪贴板"),
        ("polish", "润色剪贴板"),
        ("explain", "解释剪贴板"),
        ("answer", "作为正式问题回答"),
    ]:
        action = QAction(title, clipboard_menu)
        action.triggered.connect(
            lambda checked=False, value=mode: on_clipboard_assistant(value)
        )
        clipboard_menu.addAction(action)

    screenshot_menu = menu.addMenu("截图")
    for mode, title in [
        ("full", "全屏快速解析"),
        ("region_question", "框选截图并提问"),
    ]:
        action = QAction(title, screenshot_menu)
        action.triggered.connect(
            lambda checked=False, value=mode: on_screenshot_analysis(value)
        )
        screenshot_menu.addAction(action)

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


# 用既有 QMenu 作为二级动作来源，构建桌宠实际显示的微型卡片菜单。
def build_pet_context_menu(
    parent: QWidget,
    *,
    character_name: str,
    **menu_kwargs: object,
) -> PetContextMenu:
    """创建环绕式右键卡片，同时保留所有既有菜单动作和子菜单。"""
    legacy_menu = build_context_menu(parent, **menu_kwargs)
    return PetContextMenu(parent, character_name, legacy_menu)
