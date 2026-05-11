from __future__ import annotations

import random
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QThread,
    QTimer,
    Signal,
    QObject,
)
from PySide6.QtGui import QAction, QCloseEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import QApplication, QInputDialog, QLabel, QWidget

from ai.context_manager import ContextManager
from ai.deepseek_client import DeepSeekClient, DeepSeekError
from ai.prompt_builder import PromptBuilder
from ai.summarizer import Summarizer
from animation.sprite_player import SpritePlayer
from app.chat_input import ChatInput
from app.context_menu import build_context_menu
from app.formal_answer_panel import FormalAnswerPanel
from app.speech_bubble import SpeechBubble
from character.behavior_controller import BehaviorController
from storage.chat_store import ChatStore
from storage.json_store import load_json, load_json_prefer_primary, save_json
from storage.memory_store import MemoryStore
from storage.usage_store import UsageStore
from utils.dwm_border import apply_transparent_window_fixes, suppress_dwm_border
from utils.logger import get_logger
from utils.time_utils import now_iso


logger = get_logger(__name__)


class ChatWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        user_message: str,
        client: DeepSeekClient,
        prompt_builder: PromptBuilder,
        context_manager: ContextManager,
        formal_qa_mode: bool,
    ) -> None:
        """初始化后台聊天任务，持有本次请求所需依赖。"""
        super().__init__()
        self.user_message = user_message
        self.client = client
        self.prompt_builder = prompt_builder
        self.context_manager = context_manager
        self.formal_qa_mode = formal_qa_mode

    def run(self) -> None:
        """在工作线程中构建消息并请求模型回复。"""
        try:
            recent_messages = self.context_manager.recent_messages(self.formal_qa_mode)
            if (
                recent_messages
                and recent_messages[-1].get("role") == "user"
                and recent_messages[-1].get("content") == self.user_message
            ):
                recent_messages = recent_messages[:-1]
            messages = self.prompt_builder.build_messages(
                self.user_message,
                recent_messages,
                formal_qa_mode=self.formal_qa_mode,
            )
            reply = self.client.chat(messages)
            self.finished.emit(reply)
        except DeepSeekError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected chat worker failure")
            self.failed.emit(f"我刚刚走神了一下：{exc}")


class ProactiveSpeakWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        client: DeepSeekClient,
        prompt_builder: PromptBuilder,
    ) -> None:
        """初始化 API 主动说话测试任务。"""
        super().__init__()
        self.client = client
        self.prompt_builder = prompt_builder

    def run(self) -> None:
        """请求模型生成一条简短、温柔的主动问候。"""
        try:
            messages = self.prompt_builder.build_messages(
                "请你主动对用户说一句简短、温柔、不打扰的陪伴问候，不要超过两句话。",
                [],
            )
            reply = self.client.chat(messages)
            self.finished.emit(reply)
        except DeepSeekError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected proactive API worker failure")
            self.failed.emit(f"测试 API 主动说话失败：{exc}")


class DesktopPetWindow(QWidget):
    def __init__(self, project_root: Path) -> None:
        """初始化桌宠主窗口、依赖模块与 UI 组件。"""
        super().__init__()
        self.project_root = project_root
        self.assets_dir = self.project_root / "assets"
        self.config_dir = self.project_root / "config"
        self.data_dir = self.project_root / "data"

        self.config_path = self.config_dir / "app_config.json"
        self.example_config_path = self.config_dir / "app_config.example.json"
        self.character_path = self.config_dir / "character_default.json"
        self.local_lines_path = self.config_dir / "local_lines.json"
        self.safety_rules_path = self.config_dir / "safety_rules.json"
        self.sprite_config_path = self.assets_dir / "sprite_config.json"
        self.chat_history_formal_path = self.data_dir / "chat_history_formal.json"
        self.chat_history_informal_path = self.data_dir / "chat_history_informal.json"
        self.summary_formal_path = self.data_dir / "conversation_summary_formal.json"
        self.summary_informal_path = self.data_dir / "conversation_summary_informal.json"
        self.memory_path = self.data_dir / "memory.json"
        self.daily_usage_path = self.data_dir / "daily_usage.json"
        self.window_state_path = self.data_dir / "window_state.json"

        self.app_config = self._load_app_config()
        self.drag_start_offset = QPoint()
        self.dragging = False
        self.mouse_press_position = QPoint()
        self.chat_thread: QThread | None = None
        self.chat_worker: QObject | None = None
        self.move_animation: QPropertyAnimation | None = None
        self.behavior_started = False
        self.exit_animation_in_progress = False
        self.allow_immediate_close = False
        self._suppress_click = False
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._open_chat_input)
        self._waiting_timer = QTimer(self)
        self._waiting_timer.setSingleShot(True)
        self._waiting_timer.timeout.connect(self._show_waiting_prompt)
        self.formal_answer_panels: list[FormalAnswerPanel] = []
        self.active_formal_answer_panel: FormalAnswerPanel | None = None
        self.pending_formal_question = ""
        self._pending_was_formal = False

        self.chat_store_formal = ChatStore(self.chat_history_formal_path)
        self.chat_store_informal = ChatStore(self.chat_history_informal_path)
        self.usage_store = UsageStore(self.daily_usage_path)
        self.memory_store = MemoryStore(self.memory_path)
        self.deepseek_client = DeepSeekClient(self.config_path, self.example_config_path)
        self.prompt_builder = PromptBuilder(
            self.character_path,
            self.safety_rules_path,
            self.memory_path,
            self.summary_formal_path,
            self.summary_informal_path,
        )
        self.context_manager = ContextManager(
            self.config_path,
            self.chat_store_formal,
            self.chat_store_informal,
            self.example_config_path,
        )
        self.summarizer_formal = Summarizer(
            self.summary_formal_path,
            self.chat_store_formal,
            self.memory_store,
            self.deepseek_client,
        )
        self.summarizer_informal = Summarizer(
            self.summary_informal_path,
            self.chat_store_informal,
            self.memory_store,
            self.deepseek_client,
        )

        self.sprite_player = SpritePlayer(self.sprite_config_path, self._ui_scale())
        self.bubble = SpeechBubble()
        self.chat_input = ChatInput()
        self.behavior_controller = BehaviorController(
            self.config_path,
            self.local_lines_path,
            self.usage_store,
            self._config_snapshot,
        )
        self.auto_move_timer = QTimer(self)
        self.auto_move_timer.timeout.connect(self._trigger_auto_move)
        self._cleanup_timer = QTimer(self)
        self._cleanup_timer.timeout.connect(self._check_time_based_cleanup)
        self._cleanup_timer.start(3_600_000)

        self._setup_window()
        self._setup_ui()
        self._connect_signals()
        self._restore_position()
        self._refresh_auto_move_timer()
        self._update_sprite(self.sprite_player.current_pixmap())
        self.sprite_player.set_action("idle")

    def _setup_window(self) -> None:
        """设置主窗口的透明、无边框和置顶属性。"""
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        if self._ui_config().get("always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setAutoFillBackground(False)
        self.setStyleSheet("DesktopPetWindow { background: transparent; border: none; }")

    def _setup_ui(self) -> None:
        """创建用于显示精灵帧的标签并设置初始尺寸。"""
        self.sprite_label = QLabel(self)
        self.sprite_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.sprite_label.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.sprite_label.setAutoFillBackground(False)
        self.sprite_label.setStyleSheet("QLabel { background: transparent; border: none; }")
        self.sprite_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        width, height = self.sprite_player.base_size()
        self.resize(width, height)
        self.sprite_label.setGeometry(0, 0, width, height)

    def _connect_signals(self) -> None:
        """连接动画、输入框和主动行为等信号。"""
        self.sprite_player.frame_changed.connect(self._update_sprite)
        self.chat_input.message_submitted.connect(self._handle_user_message)
        self.behavior_controller.speak_requested.connect(self._handle_behavior_speak)

    def showEvent(self, event) -> None:  # noqa: N802
        """窗口首次显示时启动主动行为控制器。"""
        super().showEvent(event)
        if not self.behavior_started:
            self.behavior_started = True
            self.behavior_controller.start()
        apply_transparent_window_fixes(self)
        pixmap = self.sprite_label.pixmap()
        if pixmap:
            self._apply_sprite_window_mask(pixmap)

    def nativeEvent(self, eventType, message) -> tuple:  # noqa: N802
        """移除 Windows DWM 在透明无边框窗口周围绘制的细线边框。"""
        ok, result = suppress_dwm_border(eventType, message)
        if ok:
            return True, result
        return super().nativeEvent(eventType, message)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """处理鼠标按下事件，用于拖拽和右键菜单。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            self.drag_start_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.mouse_press_position = event.globalPosition().toPoint()
            if self.move_animation and self.move_animation.state() == QPropertyAnimation.State.Running:
                self.move_animation.stop()
                self.sprite_player.set_action("idle")
        elif event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """处理鼠标移动事件，实现拖拽桌宠。"""
        if event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self.mouse_press_position
            if delta.manhattanLength() > 6:
                self.dragging = True
                self.move(event.globalPosition().toPoint() - self.drag_start_offset)
        super().mouseMoveEvent(event)

    def moveEvent(self, event) -> None:  # noqa: N802
        """窗口位置变化时同步悬浮气泡和输入框的位置。"""
        super().moveEvent(event)
        self._sync_floating_widgets()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """处理鼠标释放事件，区分点击聊天和拖拽结束；双击通过计时器抑制单击。"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self.dragging:
                self._save_window_position()
            elif self._ui_config().get("click_to_chat", True):
                if self._suppress_click:
                    self._suppress_click = False
                else:
                    self._click_timer.start(QApplication.doubleClickInterval())
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """双击人物视为回复/打招呼；若在主动问候后窗口内则回复 feedback 话术。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop()
            self._suppress_click = True
            if self.behavior_controller.is_within_proactive_reply_window():
                reply = self.behavior_controller.pick_feedback_line()
            else:
                reply = self.behavior_controller.pick_reply_line()
            if reply:
                self.behavior_controller.notify_user_interaction()
                self.sprite_player.set_action("waving")
                self._display_message(reply, 7000, "system")
        super().mouseDoubleClickEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """关闭窗口前保存位置并安全回收后台线程。"""
        if not self.allow_immediate_close:
            event.ignore()
            self.request_exit()
            return
        self._cleanup_timer.stop()
        self._destroy_formal_answer_panels()
        self._save_window_position()
        self.bubble.hide()
        self.chat_input.hide()
        if self.chat_thread and self.chat_thread.isRunning():
            self.chat_thread.quit()
            self.chat_thread.wait(1000)
        super().closeEvent(event)
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _show_context_menu(self, global_pos: QPoint) -> None:
        """在指定屏幕坐标位置弹出右键菜单。"""
        menu = build_context_menu(
            self,
            test_action_handler=self._handle_test_action,
            on_test_move_left=self._test_move_left,
            on_test_move_right=self._test_move_right,
            on_test_jump=self._test_jump,
            on_test_proactive_speak=self._test_proactive_speak_once,
            on_test_api_proactive_speak=self._test_api_proactive_speak_once,
            on_test_poetry=self._test_poetry,
            on_request_exit=self.request_exit,
            current_scale=self._ui_scale(),
            do_not_disturb=bool(self._behavior_config().get("do_not_disturb", False)),
            auto_move=bool(self._ui_config().get("enable_free_move", False)),
            api_chat_enabled=bool(self._api_config().get("enable_chat_api", True)),
            formal_qa_mode=self._formal_qa_enabled(),
            formal_answer_display=self._formal_answer_display_mode(),
            on_set_scale=self._set_scale,
            on_custom_scale=self._open_scale_dialog,
            on_toggle_dnd=self._toggle_do_not_disturb,
            on_toggle_auto_move=self._toggle_auto_move,
            on_toggle_api_chat=self._toggle_api_chat,
            on_toggle_formal_qa_mode=self._toggle_formal_qa_mode,
            on_set_formal_answer_display=self._set_formal_answer_display,
            on_toggle_always_on_top=self._toggle_always_on_top,
            on_reload_config=self._reload_config,
            always_on_top=bool(self._ui_config().get("always_on_top", True)),
            show_test_menu=bool(self._ui_config().get("show_test_menu", False)),
            show_clear_menu=bool(self._ui_config().get("show_clear_menu", False)),
            on_clear_informal_chat=self._clear_informal_chat_history,
            on_clear_formal_chat=self._clear_formal_chat_history,
        )
        menu.exec(global_pos)

    def _handle_test_action(self, action_name: str) -> None:
        """响应菜单中的测试动作切换请求。"""
        if action_name == "idle":
            self.sprite_player.set_action("idle")
            return
        self.sprite_player.set_action(action_name, fallback_action="idle", force_single_cycle=True)

    def request_exit(self) -> None:
        """请求优雅退出：播放 waving 并显示道别语，再关闭窗口。"""
        if self.allow_immediate_close or self.exit_animation_in_progress:
            return

        self.exit_animation_in_progress = True
        self.chat_input.hide()
        farewell = self.behavior_controller.pick_farewell_line()
        self.sprite_player.set_action("waving", fallback_action="idle", force_single_cycle=True)
        duration_ms = self.sprite_player.action_duration_ms("waving", force_single_cycle=True)
        if farewell:
            self.bubble.show_message(farewell, self.geometry(), duration_ms + 400, "system")
        else:
            self.bubble.hide()
        QTimer.singleShot(duration_ms + 50, self._finalize_exit)

    def _finalize_exit(self) -> None:
        """在退出动作播放完成后真正关闭程序。"""
        self.allow_immediate_close = True
        self.close()

    def _test_proactive_speak_once(self) -> None:
        """手动触发一次主动说话，便于测试气泡与动作。"""
        if self.behavior_controller.trigger_test_speak():
            return
        self._display_message("本地话术里暂时没有可测试的内容。", 3200, "system")

    def _test_move_left(self) -> None:
        """手动测试人物向左平滑移动。"""
        QTimer.singleShot(120, lambda: self._start_horizontal_move_test(-140))

    def _test_move_right(self) -> None:
        """手动测试人物向右平滑移动。"""
        QTimer.singleShot(120, lambda: self._start_horizontal_move_test(140))

    def _test_jump(self) -> None:
        """手动测试人物原地跳跃。"""
        QTimer.singleShot(120, self._run_jump_test)

    def _run_jump_test(self) -> None:
        """在菜单关闭后真正执行一次原地跳跃测试。"""
        if self._movement_locked():
            return
        screen = self._current_screen()
        if not screen:
            return
        self._start_jump_auto_move(self.pos(), screen.availableGeometry())

    def _test_api_proactive_speak_once(self) -> None:
        """手动触发一次 API 主动说话，便于测试联网和主动气泡。"""
        if self._chat_in_progress():
            self._display_message("我还在忙上一条请求呢，等我一下下。", 3200, "system")
            return
        if not self.deepseek_client.is_configured():
            self._display_message(
                "还没有配置可用的 API key，暂时没法测试 API 主动说话哦。",
                4200,
                "system",
            )
            return

        self.sprite_player.set_action("waving")
        self._display_message("我在努力思考，想要和你打个招呼。", 2800, "system")
        self._start_proactive_api_worker()

    def _test_poetry(self) -> None:
        """念一首诗，将换行诗文字展示为气泡消息。"""
        line = self.behavior_controller.pick_poetry_line()
        if line:
            self.sprite_player.set_action("running", force_single_cycle=True)
            self._display_message(line, 12000, "system")

    def _set_scale(self, scale: float) -> None:
        """设置人物显示缩放比例并持久化到配置文件。"""
        normalized_scale = max(0.3, min(scale, 3.0))
        self.app_config.setdefault("ui", {})["scale"] = round(normalized_scale, 2)
        self.sprite_player.set_scale(normalized_scale)
        self._resize_for_sprite()
        self._save_app_config()
        self._display_message(f"人物大小已调整为 {normalized_scale:.2f}x。", 2800, "system")

    def _open_scale_dialog(self) -> None:
        """弹出自定义缩放输入框，让用户手动设置人物大小。"""
        current_scale = self._ui_scale()
        new_scale, accepted = QInputDialog.getDouble(
            self,
            "自定义缩放",
            "请输入人物缩放倍数：",
            value=current_scale,
            minValue=0.3,
            maxValue=3.0,
            decimals=2,
        )
        if accepted:
            self._set_scale(new_scale)

    def _toggle_do_not_disturb(self, enabled: bool) -> None:
        """切换免打扰模式并保存配置。"""
        self.app_config.setdefault("behavior", {})["do_not_disturb"] = enabled
        self._save_app_config()
        if enabled and self.bubble.source == "proactive":
            self.bubble.hide()
        self._display_message("小胡接下来不会说话了。" if enabled else "来和小胡聊天吧。", 3000, "system")

    def _toggle_auto_move(self, enabled: bool) -> None:
        """切换自主移动功能并刷新定时器。"""
        self.app_config.setdefault("ui", {})["enable_free_move"] = enabled
        self._save_app_config()
        self._refresh_auto_move_timer()
        self._display_message("小胡跑起来了！" if enabled else "我不会乱动啦。", 3000, "system")

    def _toggle_api_chat(self, enabled: bool) -> None:
        """切换用户聊天时是否调用外部 API。"""
        self.app_config.setdefault("api", {})["enable_chat_api"] = enabled
        self._save_app_config()
        self._display_message("我变的更聪明了。" if enabled else "我好像变笨了。", 3200, "system")

    def _toggle_formal_qa_mode(self, enabled: bool) -> None:
        """切换正式问答模式。"""
        self._chat_config()["formal_qa_mode"] = enabled
        self._save_app_config()
        if not enabled:
            self._destroy_formal_answer_panels()
        self._display_message(
            "我会更加认真地回答你的问题。" if enabled else "现在就简简单单的聊天吧。",
            3200,
            "system",
        )

    def _set_formal_answer_display(self, mode: str) -> None:
        """切换正式问答多回答显示方式。"""
        normalized_mode = mode if mode in {"new_panel", "append"} else "new_panel"
        self._chat_config()["formal_answer_display"] = normalized_mode
        self._save_app_config()
        message = (
            "正式问答将为每个新问题保留并新建文本框。"
            if normalized_mode == "new_panel"
            else "正式问答将把新回答追加到同一个文本框。"
        )
        self._display_message(message, 3600, "system")

    def _toggle_always_on_top(self, enabled: bool) -> None:
        """切换窗口置顶状态，开启时回复 return_after_idle，关闭时回复 ignored。"""
        self._ui_config()["always_on_top"] = enabled
        self._save_app_config()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.show()
        self.chat_input.set_always_on_top(enabled)
        if enabled:
            reply = self.behavior_controller.pick_return_after_idle_line()
        else:
            reply = self.behavior_controller.pick_ignored_line()
        if reply:
            self._display_message(reply, 5000, "system")

    def _clear_chat_history(self) -> None:
        """清空正式与非正式聊天历史及对应摘要数据。"""
        default_summary = {
            "summary": "",
            "covered_message_count": 0,
            "highlights": [],
            "last_updated": "",
        }
        for store, summary_path in [
            (self.chat_store_formal, self.summary_formal_path),
            (self.chat_store_informal, self.summary_informal_path),
        ]:
            store.clear_history()
            save_json(summary_path, default_summary)
        self._display_message("聊天记录已经清空啦。", 3500, "system")

    def _clear_informal_chat_history(self) -> None:
        """清空非正式聊天历史；若配置开启则在清空前强制总结。"""
        if self._chat_config().get("force_summarize_before_clear", True):
            self.summarizer_informal.maybe_summarize(0, force=True)
        self.chat_store_informal.clear_history()
        self.chat_store_informal.update_last_cleaned_at(now_iso())
        self._display_message("非正式聊天记录已经清空啦。", 3500, "system")

    def _clear_formal_chat_history(self) -> None:
        """清空正式问答聊天历史；若配置开启则在清空前强制总结。"""
        if self._chat_config().get("force_summarize_before_clear", True):
            self.summarizer_formal.maybe_summarize(0, force=True)
        self.chat_store_formal.clear_history()
        self.chat_store_formal.update_last_cleaned_at(now_iso())
        self._display_message("正式问答记录已经清空啦。", 3500, "system")

    def _reload_config(self) -> None:
        """重新读取配置文件，并刷新动画和行为控制状态。"""
        self.app_config = self._load_app_config()
        self.sprite_player.set_scale(self._ui_scale())
        self.sprite_player.load()
        self._setup_window()
        self._resize_for_sprite()
        self._refresh_auto_move_timer()
        self.behavior_controller.reload()
        self._display_message("配置已经重新加载。", 3500, "system")

    def _open_chat_input(self) -> None:
        """在宠物附近打开输入框；若有主动气泡则先关闭。"""
        if self.bubble.source == "proactive":
            self.bubble.hide()
        if self._chat_in_progress():
            self._display_message("我还在想上一条呢，等我一下下。", 3200, "system")
            return
        self.behavior_controller.notify_user_interaction()
        self.chat_input.set_always_on_top(bool(self._ui_config().get("always_on_top", True)))
        self.chat_input.show_near(self.geometry())
        self._waiting_timer.start(30_000)

    _poetry_keywords = {"诗", "诗歌", "写诗", "念诗", "吟诗", "背诗", "来首", "作诗", "赋诗"}

    def _handle_user_message(self, message: str) -> None:
        """处理用户提交的消息，并决定走占位回复还是 API 回复。"""
        self._waiting_timer.stop()
        self.behavior_controller.notify_user_interaction()
        store = self._active_chat_store()
        store.append_message("user", message)
        self._pending_was_formal = self._formal_qa_enabled()
        if self._pending_was_formal:
            self.pending_formal_question = message

        if (
            self._is_poetry_request(message)
            and not self._api_chat_enabled()
            and not self._formal_qa_enabled()
            and not self._ui_config().get("enable_free_move", False)
            and not self._ui_config().get("always_on_top", True)
        ):
            poetry_line = self.behavior_controller.pick_poetry_line()
            if poetry_line:
                store.append_message("assistant", poetry_line)
                self.sprite_player.set_action("running", force_single_cycle=True)
                self._show_answer_output(poetry_line, source="assistant", question=message)
                return

        self._display_message("我收到啦，让我想一想。", 3200, "system")
        self.sprite_player.set_action("review" if len(message) > 24 else "running")

        if not self._api_chat_enabled():
            reply = self._generate_local_reply(message, formal_qa_mode=self._formal_qa_enabled())
            store.append_message("assistant", reply)
            self.sprite_player.set_action("idle")
            self._show_answer_output(reply, source="assistant", question=message)
            return

        if not self.deepseek_client.is_configured():
            reply = (
                "我已经收到你说的话啦。先在 config/app_config.json 里填好 DeepSeek API key，"
                "或者先关闭“聊天接入 API”。"
            )
            store.append_message("assistant", reply)
            self.sprite_player.set_action("failed")
            self._show_answer_output(reply, source="assistant", question=message)
            return

        self._start_chat_worker(message)

    def _is_poetry_request(self, message: str) -> bool:
        """检查用户消息是否包含念诗/写诗相关的关键词。"""
        return any(kw in message for kw in self._poetry_keywords)

    def _generate_local_reply(self, message: str, formal_qa_mode: bool = False) -> str:
        """在本地模式下按当前问答风格生成回复。"""
        stripped_message = message.strip()
        if not stripped_message:
            return "我在这里哦。"
        if formal_qa_mode:
            if "?" in stripped_message or "？" in stripped_message:
                return (
                    "我先认真回答你一下：现在我没有接入外部问答能力，所以没法像联网模式那样给你完整检索和推理结果。"
                    "不过如果你愿意，我仍然可以基于你提供的信息，帮你一起拆问题、列思路、整理步骤。"
                )
            return (
                f"我已经完整记住你刚刚说的内容：{stripped_message[:60]}。"
                "当前是正式问答模式，但我现在走的是本地回复，所以没法给出特别深入的答案。"
                "如果你打开 API，我就可以尽量给你更完整、更有条理的回答。"
            )
        if "?" in stripped_message or "？" in stripped_message:
            return "这个问题我先记住啦。现在我没有连上 API，所以只能先陪你整理思路；如果你愿意，我也可以继续听你说。"
        if any(keyword in stripped_message for keyword in ["你好", "在吗", "嗨", "hi", "hello"]):
            return "我在这里哦，很高兴你来找我。"
        if any(keyword in stripped_message for keyword in ["累", "烦", "难", "焦虑", "紧张"]):
            return "抱抱你呀，先别急，我们可以一点点来。虽然我现在没接 API，但我会认真陪着你。"
        return f"我收到啦：{stripped_message[:30]}。现在我先用本地模式陪你，如果你想要更完整的回答，可以再打开 API。"

    def _start_chat_worker(self, message: str) -> None:
        """创建后台线程执行模型请求，避免阻塞界面。"""
        if self.chat_thread and self.chat_thread.isRunning():
            return

        self.chat_thread = QThread(self)
        self.chat_worker = ChatWorker(
            message,
            self.deepseek_client,
            self.prompt_builder,
            self.context_manager,
            self._formal_qa_enabled(),
        )
        self.chat_worker.moveToThread(self.chat_thread)
        self.chat_thread.started.connect(self.chat_worker.run)
        self.chat_worker.finished.connect(self._on_chat_success)
        self.chat_worker.failed.connect(self._on_chat_failure)
        self.chat_worker.finished.connect(self.chat_thread.quit)
        self.chat_worker.failed.connect(self.chat_thread.quit)
        self.chat_thread.finished.connect(self._cleanup_chat_thread)
        self.chat_thread.start()

    def _start_proactive_api_worker(self) -> None:
        """创建后台线程执行 API 主动说话测试。"""
        if self.chat_thread and self.chat_thread.isRunning():
            return

        self.chat_thread = QThread(self)
        self.chat_worker = ProactiveSpeakWorker(
            self.deepseek_client,
            self.prompt_builder,
        )
        self.chat_worker.moveToThread(self.chat_thread)
        self.chat_thread.started.connect(self.chat_worker.run)
        self.chat_worker.finished.connect(self._on_proactive_api_success)
        self.chat_worker.failed.connect(self._on_proactive_api_failure)
        self.chat_worker.finished.connect(self.chat_thread.quit)
        self.chat_worker.failed.connect(self.chat_thread.quit)
        self.chat_thread.finished.connect(self._cleanup_chat_thread)
        self.chat_thread.start()

    def _cleanup_chat_thread(self) -> None:
        """在线程结束后清理工作对象和线程对象。"""
        if self.chat_worker:
            self.chat_worker.deleteLater()
            self.chat_worker = None
        if self.chat_thread:
            self.chat_thread.deleteLater()
            self.chat_thread = None

    def _on_chat_success(self, reply: str) -> None:
        """处理模型成功返回后的界面更新与消息落盘。"""
        cleaned_reply = reply.strip() or "我在这里哦。"
        store = self.chat_store_formal if self._pending_was_formal else self.chat_store_informal
        store.append_message("assistant", cleaned_reply)
        self.sprite_player.set_action("idle")
        self._show_answer_output(
            cleaned_reply,
            source="assistant",
            question=self.pending_formal_question,
        )
        self.pending_formal_question = ""
        was_formal = self._pending_was_formal
        self._pending_was_formal = False
        threading.Thread(target=self._maybe_summarize, args=(was_formal,), daemon=True).start()

    def _on_chat_failure(self, error_message: str) -> None:
        """处理模型请求失败后的动作和气泡提示。"""
        self.sprite_player.set_action("failed")
        self._display_message(error_message, 12000, "assistant")
        self.pending_formal_question = ""

    def _on_proactive_api_success(self, reply: str) -> None:
        """处理 API 主动说话测试成功后的界面更新。"""
        cleaned_reply = reply.strip() or "我在这里哦。"
        self.sprite_player.set_action("idle")
        self._display_message(cleaned_reply, 12000, "assistant")

    def _on_proactive_api_failure(self, error_message: str) -> None:
        """处理 API 主动说话测试失败后的界面更新。"""
        self.sprite_player.set_action("failed")
        self._display_message(error_message, 12000, "assistant")

    def _maybe_summarize(self, formal_qa_mode: bool = False) -> None:
        """在后台线程中尝试触发对应模式的聊天摘要。"""
        try:
            trigger_rounds = int(self._api_config().get("summary_trigger_rounds", 12))
            if formal_qa_mode:
                self.summarizer_formal.maybe_summarize(trigger_rounds)
            else:
                self.summarizer_informal.maybe_summarize(trigger_rounds)
        except Exception:  # noqa: BLE001
            logger.exception("Background summarization failed")

    def _handle_behavior_speak(self, text: str, duration_ms: int, action_name: str) -> None:
        """响应主动行为控制器的说话请求。"""
        if self._chat_in_progress() or self.chat_input.isVisible():
            return
        self.sprite_player.set_action(action_name)
        self._display_message(text, duration_ms, "proactive")

    def _display_message(self, text: str, duration_ms: int, source: str) -> None:
        """通过气泡组件显示一条消息。"""
        self.bubble.set_always_on_top(bool(self._ui_config().get("always_on_top", True)))
        self.bubble.show_message(text, self.geometry(), duration_ms, source)
        self._sync_floating_widgets()

    def _show_waiting_prompt(self) -> None:
        """聊天输入框打开后长时间未回复时，显示 waiting 话术并重启计时器。"""
        if not self.chat_input.isVisible():
            return
        reply = self.behavior_controller.pick_waiting_line()
        if reply:
            self._display_message(reply, 6000, "system")
        self._waiting_timer.start(25_000)

    def _show_answer_output(self, text: str, source: str, question: str = "") -> None:
        """根据当前模式决定用气泡还是正式问答面板展示回答。"""
        if source == "assistant" and self._formal_qa_enabled():
            self._show_formal_answer_panel(question, text)
            return
        duration_ms = 15000 if source == "assistant" else 9000
        self._display_message(text, duration_ms, source)

    def _show_formal_answer_panel(self, question: str, answer: str) -> None:
        """按正式问答显示方式展示回答，支持新建面板或追加内容。"""
        display_mode = self._formal_answer_display_mode()
        if (
            display_mode == "append"
            and self.active_formal_answer_panel is not None
            and self.active_formal_answer_panel.isVisible()
        ):
            self.active_formal_answer_panel.append_entry(question, answer)
            return

        panel = FormalAnswerPanel(title="正式问答")
        panel_id = id(panel)
        panel.destroyed.connect(
            lambda *_args, owned_panel_id=panel_id: self._on_formal_answer_panel_destroyed(
                owned_panel_id
            )
        )
        content = FormalAnswerPanel.format_entry(question, answer)
        panel.set_content("正式问答", content, self.geometry(), len(self.formal_answer_panels))
        self.formal_answer_panels.append(panel)
        self.active_formal_answer_panel = panel

    def _destroy_formal_answer_panels(self) -> None:
        """关闭并销毁所有正式问答面板。"""
        panels = list(self.formal_answer_panels)
        self.formal_answer_panels.clear()
        self.active_formal_answer_panel = None
        for panel in panels:
            panel.close()

    def _on_formal_answer_panel_destroyed(self, panel_id: int) -> None:
        """在正式问答面板销毁后移除引用，避免关闭后残留对象。"""
        self.formal_answer_panels = [
            panel for panel in self.formal_answer_panels if id(panel) != panel_id
        ]
        if self.active_formal_answer_panel and id(self.active_formal_answer_panel) == panel_id:
            self.active_formal_answer_panel = (
                self.formal_answer_panels[-1] if self.formal_answer_panels else None
            )

    def _update_sprite(self, pixmap) -> None:
        """把最新精灵帧绘制到主窗口标签上。"""
        self.sprite_label.setPixmap(pixmap)
        self._resize_for_sprite()

    def _resize_for_sprite(self) -> None:
        """根据当前精灵帧尺寸同步调整窗口大小。"""
        pixmap = self.sprite_label.pixmap()
        if not pixmap:
            return
        self.resize(pixmap.width(), pixmap.height())
        self.sprite_label.setGeometry(0, 0, pixmap.width(), pixmap.height())
        self._apply_sprite_window_mask(pixmap)
        self._sync_floating_widgets()

    def _apply_sprite_window_mask(self, pixmap: QPixmap) -> None:
        """按精灵帧的透明区域裁剪窗口，避免系统沿矩形外接框绘制边框。"""
        mask = pixmap.mask()
        if mask.isNull():
            self.clearMask()
            self.sprite_label.clearMask()
            return
        self.setMask(mask)
        self.sprite_label.setMask(mask)

    def _restore_position(self) -> None:
        """恢复上次窗口位置；首次启动则放到屏幕右下角。"""
        state = load_json(self.window_state_path, {"x": None, "y": None})
        ui = self._ui_config()
        remember = ui.get("remember_last_position", True)
        if remember and state.get("x") is not None and state.get("y") is not None:
            saved_position = QPoint(int(state["x"]), int(state["y"]))
            if self._position_visible_on_any_screen(saved_position):
                self.move(saved_position)
                return
            logger.warning(
                "Saved window position is outside visible screens: x=%s, y=%s. Falling back.",
                state.get("x"),
                state.get("y"),
            )

        screen = QApplication.primaryScreen()
        if not screen:
            self.move(50, 50)
            return
        available = screen.availableGeometry()
        width, height = self.sprite_player.base_size()
        margin = 30
        self.move(
            available.right() - width - margin,
            available.bottom() - height - margin,
        )

    def _save_window_position(self) -> None:
        """保存当前窗口位置到本地状态文件。"""
        save_json(self.window_state_path, {"x": self.x(), "y": self.y()})

    def _position_visible_on_any_screen(self, position: QPoint) -> bool:
        """判断窗口放在给定坐标后，是否至少有一部分仍位于某个屏幕可见区域内。"""
        window_rect = QRect(position, self.size())
        for screen in QApplication.screens():
            if screen.availableGeometry().intersects(window_rect):
                return True
        return False

    def _refresh_auto_move_timer(self) -> None:
        """根据配置决定是否开启自主移动定时器。"""
        if self._ui_config().get("enable_free_move", False):
            self.auto_move_timer.start(random.randint(15_000, 28_000))
        else:
            self.auto_move_timer.stop()

    def _trigger_auto_move(self) -> None:
        """随机触发一次桌宠横向移动动画。"""
        self._refresh_auto_move_timer()
        if self._chat_in_progress() or self._movement_locked():
            return
        screen = self._current_screen()
        if not screen:
            return
        available = screen.availableGeometry()
        current = self.pos()
        if random.random() < 0.35:
            self._start_jump_auto_move(current, available)
            return

        delta = random.choice([-140, -100, 100, 140])
        self._start_horizontal_move_test(delta, available=available)

    def _start_horizontal_move_test(self, delta_x: int, available: QRect | None = None) -> None:
        """执行一次平滑的左右移动测试或自主移动。"""
        if self._movement_locked():
            return

        if not available:
            screen = self._current_screen()
            if not screen:
                return
            available = screen.availableGeometry()

        self._stop_active_move_animation()
        current = self.pos()
        target_x = max(available.left(), min(current.x() + delta_x, available.right() - self.width()))
        target = QPoint(target_x, max(available.top(), min(current.y(), available.bottom() - self.height())))

        if target == current:
            return

        action = "running_right" if target.x() > current.x() else "running_left"
        self.sprite_player.set_action(action)
        self.move_animation = QPropertyAnimation(self, b"pos", self)
        self.move_animation.setDuration(1200)
        self.move_animation.setStartValue(current)
        self.move_animation.setEndValue(target)
        self.move_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.move_animation.finished.connect(self._finish_auto_move)
        self.move_animation.start()

    def _start_jump_auto_move(self, current: QPoint, available: QRect) -> None:
        """执行一次带 jumping 动作的自主跳跃。"""
        self._stop_active_move_animation()
        jump_height = max(24, self.height() // 2)
        peak_y = max(available.top(), current.y() - jump_height)
        peak = QPoint(current.x(), peak_y)

        self.sprite_player.set_action("jumping", fallback_action="idle", force_single_cycle=True)
        duration_ms = self.sprite_player.action_duration_ms("jumping", force_single_cycle=True)

        self.move_animation = QPropertyAnimation(self, b"pos", self)
        self.move_animation.setDuration(duration_ms)
        self.move_animation.setStartValue(current)
        self.move_animation.setKeyValueAt(0.5, peak)
        self.move_animation.setEndValue(current)
        self.move_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.move_animation.finished.connect(self._finish_auto_move)
        self.move_animation.start()

    def _finish_auto_move(self) -> None:
        """在自主移动结束后恢复 idle 动作并保存位置。"""
        self.sprite_player.set_action("idle")
        self.move_animation = None
        self._save_window_position()
        self._sync_floating_widgets()

    def _stop_active_move_animation(self) -> None:
        if self.move_animation and self.move_animation.state() == QPropertyAnimation.State.Running:
            self.move_animation.stop()
        self.move_animation = None

    def _movement_locked(self) -> bool:
        return self.dragging or self.exit_animation_in_progress

    def _current_screen(self):
        anchor_point = self.frameGeometry().center()
        screen = QApplication.screenAt(anchor_point)
        return screen or QApplication.primaryScreen()

    def _sync_floating_widgets(self) -> None:
        """让气泡和输入框跟随角色当前位置。"""
        anchor_rect = self.geometry()
        if self.bubble.isVisible():
            self.bubble.reposition(anchor_rect)
        if self.chat_input.isVisible():
            self.chat_input.reposition(anchor_rect)

    def _chat_in_progress(self) -> bool:
        """判断当前是否仍有聊天请求在后台执行。"""
        return bool(self.chat_thread and self.chat_thread.isRunning())

    def _api_chat_enabled(self) -> bool:
        """判断当前用户聊天是否允许接入外部 API。"""
        return bool(self._api_config().get("enable_chat_api", True))

    def _formal_qa_enabled(self) -> bool:
        """判断当前是否开启正式问答模式。"""
        return bool(self._chat_config().get("formal_qa_mode", False))

    def _formal_answer_display_mode(self) -> str:
        """读取正式问答多回答显示方式。"""
        mode = str(self._chat_config().get("formal_answer_display", "new_panel"))
        return mode if mode in {"new_panel", "append"} else "new_panel"

    def _ui_scale(self) -> float:
        """读取并返回当前 UI 缩放比例。"""
        return float(self._ui_config().get("scale", 1.0) or 1.0)

    def _ui_config(self) -> dict[str, Any]:
        """返回 UI 配置字典，不存在时自动补默认节点。"""
        return self.app_config.setdefault("ui", {})

    def _behavior_config(self) -> dict[str, Any]:
        """返回行为配置字典，不存在时自动补默认节点。"""
        return self.app_config.setdefault("behavior", {})

    def _api_config(self) -> dict[str, Any]:
        """返回 API 配置字典，不存在时自动补默认节点。"""
        return self.app_config.setdefault("api", {})

    def _chat_config(self) -> dict[str, Any]:
        """返回聊天配置字典，不存在时自动补默认节点。"""
        return self.app_config.setdefault("chat", {})

    def _active_chat_store(self) -> ChatStore:
        """返回当前模式对应的聊天存储实例。"""
        return self.chat_store_formal if self._formal_qa_enabled() else self.chat_store_informal

    def _check_time_based_cleanup(self) -> None:
        """定期检查正式/非正式对话是否超过清理间隔，若超过则先摘要再清空消息。"""
        if self._chat_in_progress():
            return
        chat_config = self._chat_config()
        formal_days = int(chat_config.get("formal_cleanup_months", 6)) * 30
        informal_days = int(chat_config.get("informal_cleanup_months", 3)) * 30
        now = now_iso()

        if self.chat_store_formal.should_trigger_time_cleanup(formal_days):
            logger.info("Triggering time-based cleanup for formal chat")
            self.summarizer_formal.maybe_summarize(0, force=True)
            self.chat_store_formal.update_last_cleaned_at(now)
            self.chat_store_formal.clear_history()

        if self.chat_store_informal.should_trigger_time_cleanup(informal_days):
            logger.info("Triggering time-based cleanup for informal chat")
            self.summarizer_informal.maybe_summarize(0, force=True)
            self.chat_store_informal.update_last_cleaned_at(now)
            self.chat_store_informal.clear_history()

    def _config_snapshot(self) -> dict[str, Any]:
        """返回当前内存中的配置快照。"""
        return self.app_config

    def _load_app_config(self) -> dict[str, Any]:
        """优先读取 app_config.json，缺失时回退到 app_config.example.json。"""
        return load_json_prefer_primary(self.config_path, self.example_config_path, {})

    def _save_app_config(self) -> None:
        """把当前内存配置写回配置文件。"""
        save_json(self.config_path, self.app_config)
