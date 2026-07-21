from __future__ import annotations

import logging
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

logger_module = types.ModuleType("utils.logger")
logger_module.get_logger = logging.getLogger
sys.modules.setdefault("utils.logger", logger_module)

from PySide6.QtCore import QAbstractAnimation  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from animation.sprite_player import SpritePlayer  # noqa: E402
from app.desktop_pet_window import (  # noqa: E402
    DesktopPetWindow,
    _finish_pet_action_if_owned,
    _set_pet_action,
)


class FakeSpritePlayer:
    """记录角色动作切换，避免测试依赖精灵素材。"""

    def __init__(self) -> None:
        """初始化动作记录。"""
        self.actions: list[tuple[tuple, dict]] = []

    def set_action(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        """记录动作请求。"""
        self.actions.append((args, kwargs))


class FakeBehaviorController:
    """提供双击回应所需的最小行为控制器接口。"""

    def __init__(self, proactive_reply: bool) -> None:
        """设置当前是否位于主动问候回应窗口。"""
        self.proactive_reply = proactive_reply
        self.proactive_responses = 0

    def is_within_proactive_reply_window(self) -> bool:
        """返回测试设定的主动回应状态。"""
        return self.proactive_reply

    def pick_feedback_line(self) -> str:
        """返回固定主动问候反馈。"""
        return "我也很开心。"

    def pick_reply_line(self) -> str:
        """返回固定普通回应。"""
        return "我在这里哦。"

    def notify_proactive_response(self) -> None:
        """记录主动问候被回应。"""
        self.proactive_responses += 1


class FakeFinishedSignal:
    """记录旧移动动画完成信号是否被解除。"""

    def __init__(self) -> None:
        """初始化断开记录。"""
        self.disconnected: list[object] = []

    def disconnect(self, callback) -> None:  # type: ignore[no-untyped-def]
        """记录被断开的回调。"""
        self.disconnected.append(callback)


class FakeMoveAnimation:
    """模拟仍在运行的移动动画。"""

    def __init__(self) -> None:
        """初始化动画状态。"""
        self.finished = FakeFinishedSignal()
        self.stopped = False

    def state(self):  # type: ignore[no-untyped-def]
        """返回运行状态。"""
        return QAbstractAnimation.State.Running

    def stop(self) -> None:
        """记录动画停止。"""
        self.stopped = True


class FakeReminderWaitWindow:
    """提供提醒延后展示所需的最小窗口状态。"""

    def __init__(self) -> None:
        """初始化为正在聊天且存在待展示提醒。"""
        self._active_reminder_reply_id = ""
        self._reminder_reply_queue = [{"id": "r-1"}]
        self.screenshot_selection_overlay = None
        self._pending_screenshot = None
        self.chat_input = types.SimpleNamespace(isVisible=lambda: False)

    def _closing_or_closed(self) -> bool:
        """测试中保持窗口可用。"""
        return False

    def _chat_in_progress(self) -> bool:
        """模拟有进行中的聊天请求。"""
        return True

    def _show_next_reminder_reply(self) -> None:
        """提供重试回调目标；本测试会拦截定时器，不会实际递归执行。"""
        DesktopPetWindow._show_next_reminder_reply(self)


class InteractionActionConflictTests(unittest.TestCase):
    """验证用户回应动作不会被通用 idle 收尾或旧移动回调覆盖。"""

    def test_double_click_starts_waving_after_mouse_event_without_settling(self) -> None:
        """双击回应延后播放挥手，且不调用互动收尾。"""
        displayed: list[tuple] = []
        fake = types.SimpleNamespace(
            _click_timer=types.SimpleNamespace(stop=lambda: None),
            _suppress_click=False,
            behavior_controller=FakeBehaviorController(proactive_reply=False),
            sprite_player=FakeSpritePlayer(),
        )
        fake._display_message = lambda *args: displayed.append(args)
        fake._show_pet_double_click_reply = (
            lambda reply: DesktopPetWindow._show_pet_double_click_reply(fake, reply)
        )

        with patch(
            "app.desktop_pet_window.QTimer.singleShot",
            side_effect=lambda _delay, callback: callback(),
        ) as single_shot:
            DesktopPetWindow._respond_to_pet_double_click(fake)

        self.assertTrue(fake._suppress_click)
        single_shot.assert_called_once()
        self.assertEqual(single_shot.call_args.args[0], 30)
        self.assertEqual(
            fake.sprite_player.actions,
            [(('waving',), {'fallback_action': 'idle', 'force_single_cycle': True})],
        )
        self.assertEqual(displayed, [("我在这里哦。", 7000, "system")])

    def test_stopping_move_disconnects_idle_completion_callback(self) -> None:
        """停止旧移动时解除完成回调，防止其覆盖后续挥手。"""
        animation = FakeMoveAnimation()
        callback = object()
        fake = types.SimpleNamespace(move_animation=animation, _finish_auto_move=callback)

        DesktopPetWindow._stop_active_move_animation(fake)

        self.assertTrue(animation.stopped)
        self.assertEqual(animation.finished.disconnected, [callback])
        self.assertIsNone(fake.move_animation)

    def test_stale_move_finished_signal_cannot_complete_newer_animation(self) -> None:
        """即使旧动画完成信号已排队，也不能结束新的动画或动作。"""
        stale_animation = object()
        current_animation = object()
        fake = types.SimpleNamespace(
            sender=lambda: stale_animation,
            move_animation=current_animation,
            _sprite_action_owner="user_reply",
            sprite_player=FakeSpritePlayer(),
            _save_window_position=lambda: None,
            _sync_floating_widgets=lambda: None,
        )

        DesktopPetWindow._finish_auto_move(fake)

        self.assertIs(fake.move_animation, current_animation)
        self.assertEqual(fake.sprite_player.actions, [])

    def test_new_non_movement_action_stops_existing_movement(self) -> None:
        """新交互动作会先停止旧移动，避免人物移动时又挥手。"""
        stopped: list[bool] = []
        fake = types.SimpleNamespace(
            move_animation=object(),
            sprite_player=FakeSpritePlayer(),
            _stop_active_move_animation=lambda: stopped.append(True),
        )

        _set_pet_action(fake, "waving", owner="user_reply")

        self.assertEqual(stopped, [True])
        self.assertEqual(fake._sprite_action_owner, "user_reply")
        self.assertEqual(fake.sprite_player.actions[0][0], ("waving",))

    def test_stale_worker_callback_does_not_overwrite_newer_action(self) -> None:
        """旧后台任务只能结束自己仍拥有的动作。"""
        fake = types.SimpleNamespace(
            move_animation=None,
            sprite_player=FakeSpritePlayer(),
            _sprite_action_owner="user_reply",
        )

        self.assertFalse(_finish_pet_action_if_owned(fake, "clipboard"))
        self.assertEqual(fake.sprite_player.actions, [])

        fake._sprite_action_owner = "clipboard"
        self.assertTrue(_finish_pet_action_if_owned(fake, "clipboard"))
        self.assertEqual(fake.sprite_player.actions[0][0], ("idle",))

    def test_menu_follow_up_interaction_does_not_settle_new_action(self) -> None:
        """二级菜单完成信号只记录互动，不能覆盖刚启动的动作。"""
        notified: list[str] = []
        settled: list[bool] = []
        fake = types.SimpleNamespace(
            behavior_controller=types.SimpleNamespace(
                notify_user_interaction=lambda source: notified.append(source)
            ),
            _settle_after_user_interaction=lambda: settled.append(True),
        )

        DesktopPetWindow._record_user_interaction(fake, "context_menu", settle=False)

        self.assertEqual(notified, ["context_menu"])
        self.assertEqual(settled, [])

    def test_delayed_double_click_reply_still_runs_after_idle_settling(self) -> None:
        """双击后的常规 idle 收尾不能误取消回应气泡和挥手。"""
        displayed: list[tuple] = []
        fake = types.SimpleNamespace(
            _sprite_action_owner="idle",
            sprite_player=FakeSpritePlayer(),
            _display_message=lambda *args: displayed.append(args),
        )

        DesktopPetWindow._show_pet_double_click_reply(fake, "我在这里哦。")

        self.assertEqual(fake.sprite_player.actions[0][0], ("waving",))
        self.assertEqual(displayed, [("我在这里哦。", 7000, "system")])

    def test_reminder_queue_waits_for_active_chat_before_showing_action(self) -> None:
        """聊天进行时提醒只排队重试，不能抢占角色动作。"""
        fake = FakeReminderWaitWindow()

        with patch("app.desktop_pet_window.QTimer.singleShot") as single_shot:
            DesktopPetWindow._show_next_reminder_reply(fake)

        single_shot.assert_called_once_with(1000, fake._show_next_reminder_reply)
        self.assertEqual(fake._reminder_reply_queue, [{"id": "r-1"}])

    def test_sprite_timer_cannot_apply_an_old_action_fallback_after_replacement(self) -> None:
        """精灵定时器只推进当前动作，旧挥手不会在之后把 review 切回 idle。"""
        app = QApplication.instance() or QApplication([])
        del app
        player = SpritePlayer(DESKTOP_PET_ROOT / "assets" / "sprite_config.json")
        frame = QPixmap(1, 1)
        player.frames_by_action = {
            "idle": [frame, frame],
            "waving": [frame, frame],
            "review": [frame, frame],
        }
        player.config = {
            "default_fps": 8,
            "actions": {
                "idle": {"loop": True},
                "waving": {"loop": False},
                "review": {"loop": True},
            },
        }
        try:
            player.set_action("waving", force_single_cycle=True)
            player.set_action("review")
            player._advance_frame()

            self.assertEqual(player.current_action, "review")
        finally:
            player.timer.stop()


if __name__ == "__main__":
    unittest.main()
