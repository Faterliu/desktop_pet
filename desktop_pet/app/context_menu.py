from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QCursor, QKeyEvent, QPainter
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


MenuActionKind = Literal["action", "toggle", "submenu", "separator"]
MenuActionPlacement = Literal["primary", "settings", "exit"]


@dataclass(frozen=True)
class MenuAction:
    """描述右键菜单中的一个动作或结构节点。"""

    action_id: str
    title: str = ""
    kind: MenuActionKind = "action"
    callback: Callable[[bool], None] | None = None
    checked: bool = False
    children: tuple["MenuAction", ...] = ()
    exclusive_group: str | None = None
    placement: MenuActionPlacement = "settings"


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
    def __init__(
        self,
        parent: QWidget,
        character_name: str,
        actions: tuple[MenuAction, ...],
    ) -> None:
        """初始化菜单卡片，并以动作模型作为唯一菜单来源。"""
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
        self._actions = actions
        self._buttons: dict[str, QPushButton | QToolButton] = {}
        self._submenu_models: dict[str, MenuAction] = {}
        self._submenus: dict[str, QMenu] = {}
        self._active_submenu: QMenu | None = None
        self._active_submenu_button: QToolButton | None = None
        self._exit_action: MenuAction | None = None
        self._always_on_top: bool | None = None

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
        self._add_model_actions()

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
        """按动作模型创建指定二级菜单，不存在时返回空值。"""
        action = self._submenu_models.get(title)
        return self._menu_for(action) if action is not None else None

    # 处理 Esc 关闭，其他按键保持 Qt 默认行为。
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        """按下 Esc 时关闭悬浮菜单卡片。"""
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)

    # 按模型中的一级位置角色渲染卡片按钮与设置子菜单。
    def _add_model_actions(self) -> None:
        """将高频动作放在一级，其余动作收纳到设置二级菜单。"""
        primary_actions = [
            action for action in self._actions if action.placement == "primary"
        ]
        settings_actions = [
            action for action in self._actions if action.placement == "settings"
        ]
        self._exit_action = next(
            (action for action in self._actions if action.placement == "exit"),
            None,
        )
        for action in primary_actions:
            self._add_model_entry(action)
        if settings_actions:
            self._add_divider()
            self._add_submenu(
                MenuAction(
                    action_id="settings",
                    title="设置",
                    kind="submenu",
                    children=tuple(settings_actions),
                    placement="primary",
                )
            )
        self._add_close_menu_button()

    # 按动作类型添加一个一级卡片入口。
    def _add_model_entry(self, action: MenuAction) -> None:
        """把模型动作转换为普通按钮、开关或二级入口。"""
        if action.kind == "submenu":
            self._add_submenu(action)
            return
        if action.kind == "toggle":
            self._add_toggle(action)
            return
        if action.kind == "action":
            self._add_action(action, danger=False)

    # 添加执行模型动作的普通卡片按钮。
    def _add_action(self, action: MenuAction, *, danger: bool) -> None:
        """添加普通按钮，并在点击时执行对应模型回调。"""
        button = self._new_button(action.title)
        if danger:
            button.setProperty("danger", "true")
            button.style().unpolish(button)
            button.style().polish(button)
        button.clicked.connect(
            lambda checked=False, target=action: self._invoke_action(target, checked)
        )
        self._add_button(action.title, button)

    # 添加只关闭当前卡片的底部按钮，避免与退出程序混淆。
    def _add_close_menu_button(self) -> None:
        """添加“关闭菜单”按钮，不触发桌宠退出流程。"""
        button = self._new_button("关闭菜单")
        button.clicked.connect(self._close_menu)
        self._add_button("关闭菜单", button)

    # 添加能显示勾选状态的一级开关按钮。
    def _add_toggle(self, action: MenuAction) -> None:
        """添加带固定位置状态开关的按钮，并保持模型状态一致。"""
        button = DndToggleButton(action.title, self)
        button.setObjectName("menu_button")
        button.setProperty("dnd_toggle", "true")
        button.setFixedHeight(32)
        button.setFixedWidth(self._button_width)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        button.setCheckable(True)
        button.setChecked(action.checked)
        button.clicked.connect(
            lambda checked=False, target=action: self._invoke_action(target, checked)
        )
        self._add_button(action.title, button)

    # 添加显示模型子菜单的卡片入口。
    def _add_submenu(self, action: MenuAction) -> None:
        """添加二级菜单入口，并为对应 QMenu 套用既有列表样式。"""
        button = MenuSubmenuButton(self)
        button.setObjectName("menu_button")
        button.setProperty("class", "menu_button")
        button.setProperty("submenu", "true")
        button.setText(action.title)
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
        self._submenu_models[action.title] = action
        self._add_button(action.title, button)

    # 在卡片按钮旁弹出模型生成的二级菜单。
    def _show_submenu(self, button: QToolButton, action: MenuAction) -> None:
        """显示二级菜单，并让 Qt 自动处理屏幕边缘位置。"""
        submenu = self._menu_for(action)
        if self._active_submenu is not None and self._active_submenu is not submenu:
            self._active_submenu.hide()
        if self._active_submenu_button is not None and self._active_submenu_button is not button:
            self._active_submenu_button.setDown(False)
        self._style_menu_tree(submenu)
        self._active_submenu = submenu
        self._active_submenu_button = button
        button.setDown(True)
        submenu.popup(button.mapToGlobal(QPoint(button.width() - 8, 0)))

    # 由动作模型按需生成并缓存真实 QMenu。
    def _menu_for(self, action: MenuAction) -> QMenu:
        """将子菜单模型递归转换为 QMenu，QMenu 仅负责二级列表显示。"""
        existing_menu = self._submenus.get(action.action_id)
        if existing_menu is not None:
            return existing_menu
        menu = QMenu(action.title, self)
        self._style_menu_tree(menu)
        exclusive_groups: dict[str, QActionGroup] = {}
        for child in action.children:
            if child.kind == "separator":
                menu.addSeparator()
                continue
            if child.kind == "submenu":
                menu.addMenu(self._menu_for(child))
                continue
            menu_action = QAction(child.title, menu)
            if child.kind == "toggle" or child.exclusive_group is not None:
                menu_action.setCheckable(True)
                menu_action.setChecked(child.checked)
            if child.exclusive_group is not None:
                group = exclusive_groups.get(child.exclusive_group)
                if group is None:
                    group = QActionGroup(menu)
                    group.setExclusive(True)
                    exclusive_groups[child.exclusive_group] = group
                group.addAction(menu_action)
            menu_action.triggered.connect(
                lambda checked=False, target=child: self._invoke_action(target, checked)
            )
            menu.addAction(menu_action)
        self._submenus[action.action_id] = menu
        if action.title in self._submenu_models:
            menu.aboutToHide.connect(
                lambda target_menu=menu: self._reset_active_submenu(target_menu)
            )
        return menu

    # 在二级菜单收起后复位对应一级按钮，避免点击卡片空白处时残留高亮。
    def _reset_active_submenu(self, submenu: QMenu) -> None:
        """在二级菜单隐藏后清除对应一级按钮的按下状态。"""
        if self._active_submenu is not submenu:
            return
        if self._active_submenu_button is not None:
            button = self._active_submenu_button
            button.setDown(False)
            cursor_position = button.mapFromGlobal(QCursor.pos())
            if not button.rect().contains(cursor_position):
                button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
            button.update()
        self._active_submenu = None
        self._active_submenu_button = None

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

    # 执行模型叶子动作并关闭卡片。
    def _invoke_action(self, action: MenuAction, checked: bool = False) -> None:
        """记录互动、关闭菜单，再执行模型绑定的业务回调。"""
        self.interacted.emit()
        self.close()
        if action.callback is not None:
            action.callback(checked)

    # 关闭当前菜单，并把它视作一次有效用户交互。
    def _close_menu(self) -> None:
        """关闭菜单卡片，不退出桌宠程序。"""
        self.interacted.emit()
        self.close()

    # 由标题栏退出按钮触发模型中的程序退出动作。
    def _request_exit(self) -> None:
        """执行退出模型动作；构建期间缺失时安全忽略。"""
        if self._exit_action is not None:
            self._invoke_action(self._exit_action)

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


# 构建桌宠右键菜单的统一动作模型。
def build_context_menu_actions(
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
) -> tuple[MenuAction, ...]:
    """根据当前配置快照和回调构建唯一的右键菜单动作树。"""
    def action(
        action_id: str,
        title: str,
        callback: Callable[[], None],
        *,
        placement: MenuActionPlacement = "settings",
    ) -> MenuAction:
        return MenuAction(
            action_id,
            title,
            callback=lambda checked=False: callback(),
            placement=placement,
        )

    def choice(
        action_id: str,
        title: str,
        value: object,
        callback: Callable[[object], None],
        *,
        checked: bool,
        group: str,
    ) -> MenuAction:
        return MenuAction(
            action_id,
            title,
            "toggle",
            callback=lambda selected=False: callback(value),
            checked=checked,
            exclusive_group=group,
        )

    actions: list[MenuAction] = [
        MenuAction(
            "clipboard",
            "剪贴板助手",
            "submenu",
            children=tuple(
                action(
                    f"clipboard_{mode}",
                    title,
                    lambda value=mode: on_clipboard_assistant(value),
                )
                for mode, title in [
                    ("summarize", "总结剪贴板"),
                    ("translate", "翻译剪贴板"),
                    ("polish", "润色剪贴板"),
                    ("explain", "解释剪贴板"),
                    ("answer", "作为正式问题回答"),
                ]
            ),
            placement="primary",
        ),
        MenuAction(
            "reminders",
            "提醒",
            "submenu",
            children=(
                action("reminder_ten_minutes", "添加 10 分钟后提醒...", on_add_ten_minute_reminder),
                action("reminder_custom_minutes", "添加自定义分钟提醒...", on_add_custom_minute_reminder),
                MenuAction("reminder_separator", kind="separator"),
                action("reminder_view_current", "查看当前提醒", on_view_current_reminders),
                action("reminder_clear_completed", "清空已完成提醒", on_clear_completed_reminders),
            ),
            placement="primary",
        ),
        MenuAction(
            "screenshot",
            "截图",
            "submenu",
            children=tuple(
                action(
                    f"screenshot_{mode}",
                    title,
                    lambda value=mode: on_screenshot_analysis(value),
                )
                for mode, title in [
                    ("full", "全屏快速解析"),
                    ("region_question", "框选截图并提问"),
                ]
            ),
            placement="primary",
        ),
        MenuAction(
            "do_not_disturb",
            "免打扰模式",
            "toggle",
            on_toggle_dnd,
            do_not_disturb,
            placement="primary",
        ),
    ]

    if show_test_menu:
        test_actions: list[MenuAction] = [
            *(
                action(
                    f"test_action_{name}",
                    title,
                    lambda value=name: test_action_handler(value),
                )
                for name, title in [
                    ("idle", "测试动作：idle"),
                    ("waving", "测试动作：waving"),
                    ("failed", "测试动作：failed"),
                    ("review", "测试动作：review"),
                    ("running", "测试动作：running"),
                ]
            ),
            MenuAction("test_movement_separator", kind="separator"),
            action("test_move_left", "测试左移", on_test_move_left),
            action("test_move_right", "测试右移", on_test_move_right),
            action("test_jump", "测试跳跃", on_test_jump),
            MenuAction("test_proactive_separator", kind="separator"),
            action("test_proactive_speak", "测试主动说话一次", on_test_proactive_speak),
            action("test_api_proactive_speak", "测试 API 主动说话一次", on_test_api_proactive_speak),
            action("test_idle_prompt", "测试空闲问候逻辑", on_test_idle_prompt),
            MenuAction("test_knowledge_separator", kind="separator"),
            action("test_knowledge_speak", "测试主动问候知识内容", on_test_knowledge_speak),
            MenuAction("test_poetry_separator", kind="separator"),
            action("test_poetry", "念一首诗", on_test_poetry),
            MenuAction("test_provider_separator", kind="separator"),
            MenuAction(
                "test_provider",
                "测试模型切换",
                "submenu",
                children=tuple(
                    choice(
                        f"test_provider_{provider}",
                        title,
                        provider,
                        on_set_api_provider,
                        checked=api_provider == provider,
                        group="test_provider",
                    )
                    for provider, title in [
                        ("deepseek", "DeepSeek"),
                        ("openai", "OpenAI GPT"),
                    ]
                ),
            ),
        ]
        actions.append(MenuAction("test", "测试", "submenu", children=tuple(test_actions)))

    actions.extend(
        (
            MenuAction(
                "scale",
                "人物缩放",
                "submenu",
                children=(
                    *(
                        choice(
                            f"scale_{scale}",
                            f"{scale:.2f}x",
                            scale,
                            on_set_scale,
                            checked=abs(current_scale - scale) < 0.001,
                            group="scale",
                        )
                        for scale in [0.75, 1.0, 1.25, 1.5, 2.0]
                    ),
                    MenuAction("scale_separator", kind="separator"),
                    action("custom_scale", "自定义缩放...", on_custom_scale),
                ),
            ),
            MenuAction("auto_move", "自主移动", "toggle", on_toggle_auto_move, auto_move),
        )
    )
    if show_chat_api_menu:
        actions.append(MenuAction("api_chat", "聊天接入 API", "toggle", on_toggle_api_chat, api_chat_enabled))
    actions.extend(
        (
            MenuAction("formal_qa", "正式问答模式", "toggle", on_toggle_formal_qa_mode, formal_qa_mode),
            MenuAction(
                "formal_answer_display",
                "正式问答显示方式",
                "submenu",
                children=tuple(
                    choice(
                        f"formal_display_{mode}",
                        title,
                        mode,
                        on_set_formal_answer_display,
                        checked=formal_answer_display == mode,
                        group="formal_answer_display",
                    )
                    for mode, title in [
                        ("new_panel", "每题新建文本框"),
                        ("append", "追加到同一文本框"),
                    ]
                ),
            ),
            MenuAction("always_on_top", "窗口置顶", "toggle", on_toggle_always_on_top, always_on_top),
        )
    )
    if show_clear_menu:
        actions.extend(
            (
                action("clear_informal_chat", "清除非正式聊天记录", on_clear_informal_chat),
                action("clear_formal_chat", "清理正式问答记录", on_clear_formal_chat),
            )
        )
    if show_reload_config:
        actions.append(action("reload_config", "重新加载配置", on_reload_config))
    actions.append(action("exit", "退出", on_request_exit, placement="exit"))
    return tuple(actions)


# 用统一动作模型构建桌宠实际显示的微型卡片菜单。
def build_pet_context_menu(
    parent: QWidget,
    *,
    character_name: str,
    actions: tuple[MenuAction, ...],
) -> PetContextMenu:
    """创建环绕式右键卡片，二级菜单按需从动作模型生成。"""
    return PetContextMenu(parent, character_name, actions)
