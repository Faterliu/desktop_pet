"""透明视频的真实解码、动作时序、失效隔离与资源回收测试。"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from qt_test_app import ensure_app  # noqa: E402

from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage, QRegion
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from animation.video_player import VideoPlayer, _DecodeWorker
from app.desktop_pet_window import DesktopPetWindow, _finish_pet_action_if_owned, _set_pet_action
from utils.sprite_mask import visible_sprite_mask


class VideoPlayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """创建同一个离屏 GUI 应用，不启动宠物业务或网络任务。"""
        cls.app = ensure_app()

    def setUp(self):
        """记录播放器以保证测试失败时同样回收子进程。"""
        self.players = []

    def tearDown(self):
        """每个场景都必须停止线程和 FFmpeg。"""
        for player in self.players:
            self.assertTrue(player.stop())
        self.app.processEvents()

    def player(self, **kwargs):
        """构建真实资源播放器，并立即纳入清理范围。"""
        player = VideoPlayer(ROOT / "assets/sprite_config.json", **kwargs)
        self.players.append(player)
        return player

    def wait_for(self, predicate, timeout=4):
        """持续处理主线程事件，超时后报告断言失败。"""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(0.003)
        self.fail("等待播放器状态超时")

    def test_real_decode_alpha_queue_bound_and_loop(self):
        """真实解码保留 Alpha，暂停消费时队列有界，循环跨越末帧。"""
        player = self.player()
        self.wait_for(lambda: player._last_index >= 0)
        self.assertTrue(player.video_enabled)
        image = player.current_pixmap().toImage()
        self.assertEqual(player.base_size(), (240, 320))
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertGreaterEqual(image.pixelColor(120, 180).alpha(), 250)
        time.sleep(0.12)
        self.assertEqual(player._worker.frames.qsize(), 6)
        player._started = time.monotonic() - 10.5
        self.wait_for(lambda: player._last_index > 241)
        self.assertEqual(player.current_action, "idle")
        self.assertLessEqual(player._worker.frames.qsize(), 6)

    def test_formal_idle_loop_has_consistent_first_and_last_composites(self):
        """有损待机的首尾在逻辑尺寸和深浅底下保持连续，并保留真实透明。"""
        import imageio_ffmpeg

        clip = json.loads((ROOT / "assets/sprite_config.json").read_text(encoding="utf-8"))["video"]["clips"]["idle"]
        result = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-threads", "2",
             "-c:v", "libvpx-vp9", "-i", str(ROOT / clip["file"]),
             "-vf", f"select=eq(n\\,0)+eq(n\\,{clip['frames'] - 1}),scale=240:320:flags=lanczos", "-fps_mode", "passthrough",
             "-pix_fmt", "rgba", "-f", "rawvideo", "pipe:1"],
            capture_output=True, check=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        frame_size = 240 * 320 * 4
        self.assertEqual(len(result.stdout), frame_size * 2)
        first, last = result.stdout[:frame_size], result.stdout[frame_size:]
        for frame in (first, last):
            self.assertEqual(min(frame[3::4]), 0)
            self.assertEqual(max(frame[3::4]), 255)
        for background in (0, 255):
            error = 0.0
            for offset in range(0, frame_size, 4):
                a, b = first[offset + 3] / 255, last[offset + 3] / 255
                for channel in range(3):
                    before = first[offset + channel] * a + background * (1 - a)
                    after = last[offset + channel] * b + background * (1 - b)
                    error += abs(before - after)
            self.assertLess(error / (240 * 320 * 3), 1.0)

    def test_waving_last_frame_duration_and_single_completion(self):
        """挥手的第 85 帧显示足一帧，约 3.58 秒结束且只报告一次。"""
        player = self.player()
        completed = []
        player.action_finished.connect(
            lambda action, serial: completed.append(
                (action, serial, player._last_index, time.monotonic() - player._started)
            )
        )
        player.set_action("waving")
        serial = player.playback_serial
        self.wait_for(lambda: bool(completed), timeout=6)
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0][:3], ("waving", serial, 85))
        self.assertGreaterEqual(completed[0][3], 86 / 24)
        self.assertLess(completed[0][3], 4.0)
        self.assertEqual(player.current_action, "idle")
        self.assertEqual(player.action_duration_ms("waving"), 3583)

    def test_mapping_and_repeated_loop_keep_progress(self):
        """思考与等待保留逻辑动作名，相同循环请求保持原播放序号。"""
        player = self.player()
        for action, clip in (("running", "thinking"), ("review", "thinking"), ("waiting", "idle")):
            player.set_action(action)
            self.assertEqual(player.current_action, action)
            self.assertEqual(player._worker.clip_name, clip)
            self.assertTrue(player._worker.loop)
            serial = player.playback_serial
            player.set_action(action)
            self.assertEqual(player.playback_serial, serial)
        player.set_action("running", force_single_cycle=True)
        self.assertGreater(player.playback_serial, serial)
        self.assertFalse(player._worker.loop)

    def test_unavailable_single_actions_settle_without_waiting(self):
        """未制作的单次动作和跳跃请求直接待机，不播放十秒占位。"""
        player = self.player()
        for action in ("failed", "sleepy", "leaf-hug", "jumping"):
            player.set_action(action, force_single_cycle=True)
            self.assertEqual(player.current_action, "idle")
            self.assertTrue(player._worker.loop)
            self.assertEqual(player.action_duration_ms(action, True), 0)
        player.set_action("failed")
        self.assertEqual(player.current_action, "idle")

    def test_walking_clips_play_once_and_report_current_media_frames(self):
        """左右行走按各自帧数播完后回待机，帧事件带当前动作和播放序号。"""
        player = self.player()
        presented = []
        completed = []
        player.frame_presented.connect(lambda *args: presented.append(args))
        player.action_finished.connect(lambda *args: completed.append((*args, player._last_index)))
        self.assertTrue(player.horizontal_movement_enabled)
        for action, clip, movement, duration, last_frame in (
            ("running_right", "walking_right", (33, 224), 11208, 268),
            ("running_left", "walking_left", (25, 198), 9000, 215),
        ):
            player.set_action(action)
            serial = player.playback_serial
            self.assertEqual(player._worker.clip_name, clip)
            self.assertFalse(player._worker.loop)
            self.assertEqual(player.movement_frame_range(action), movement)
            self.assertEqual(player.action_duration_ms(action), duration)
            self.wait_for(lambda: player._last_index >= 0)
            player._started -= 12
            self.wait_for(lambda: (action, serial, last_frame) in completed)
            self.assertEqual(player.current_action, "idle")
            frames = [index for name, seq, index in presented if name == action and seq == serial]
            self.assertEqual(frames, sorted(set(frames)))
            self.assertEqual(frames[-1], last_frame)

    def test_three_clip_config_still_disables_unavailable_walking(self):
        """旧三视频配置仍可播放，缺少左右行走时隐藏移动能力。"""
        config = json.loads((ROOT / "assets/sprite_config.json").read_text(encoding="utf-8"))
        del config["video"]["clips"]["happy"]
        config["video"]["actions"]["happy"] = "idle"
        for direction in ("left", "right"):
            del config["video"]["clips"][f"walking_{direction}"]
            config["video"]["actions"][f"running_{direction}"] = "idle"
        with patch("animation.video_player.load_json", return_value=config):
            player = self.player()
        self.wait_for(lambda: player._last_index >= 0)
        self.assertTrue(player.video_enabled)
        self.assertFalse(player.horizontal_movement_enabled)
        player.set_action("running_right", force_single_cycle=True)
        self.assertEqual(player.current_action, "idle")
        self.assertEqual(player.action_duration_ms("running_right"), 0)

    def test_happy_plays_once_and_respects_fallback(self):
        """开心默认单次播放，末帧完成后按业务要求回到待机或输入等待。"""
        player = self.player()
        completed = []
        player.action_finished.connect(lambda *args: completed.append((*args, player._last_index)))
        for fallback in ("idle", "waiting"):
            player.set_action("happy", fallback_action=fallback)
            serial = player.playback_serial
            self.assertEqual(player.current_action, "happy")
            self.assertEqual(player._worker.clip_name, "happy")
            self.assertFalse(player._worker.loop)
            self.assertEqual(player.action_duration_ms("happy"), 10042)
            self.wait_for(lambda: player._last_index >= 0)
            self.assertEqual(player.current_pixmap().toImage().pixelColor(0, 0).alpha(), 0)
            player._started -= 11
            self.wait_for(lambda: ("happy", serial, 240) in completed)
            self.assertEqual(player.current_action, fallback)
            self.assertTrue(player._worker.loop)

    def test_happy_restart_and_interruption_ignore_old_completion(self):
        """重复开心重新播放，新思考开始后旧开心的完成和错误不能覆盖它。"""
        player = self.player()
        fake = types.SimpleNamespace(sprite_player=player)
        _set_pet_action(fake, "happy", owner="chat")
        old_serial = player.playback_serial
        _set_pet_action(fake, "happy", owner="chat")
        self.assertGreater(player.playback_serial, old_serial)
        _set_pet_action(fake, "review", owner="screenshot")
        DesktopPetWindow._on_video_action_finished(fake, "happy", old_serial)
        player._fail(old_serial, "旧开心解码失败")
        self.assertTrue(player.video_enabled)
        self.assertEqual(player.current_action, "review")
        self.assertEqual(fake._sprite_action_owner, "screenshot")

    def test_happy_api_wait_keeps_chat_ownership_for_worker_completion(self):
        """开心播完后的等待仍属于聊天，API 完成可以正常恢复待机。"""
        player = self.player()
        fake = types.SimpleNamespace(sprite_player=player)
        _set_pet_action(fake, "happy", fallback_action="waiting", owner="chat")
        DesktopPetWindow._on_video_action_finished(fake, "happy", player.playback_serial)
        self.assertEqual(player.current_action, "waiting")
        self.assertEqual(fake._sprite_action_owner, "chat")
        self.assertTrue(_finish_pet_action_if_owned(fake, "chat"))
        self.assertEqual(player.current_action, "idle")

    def test_old_config_without_happy_still_plays_and_missing_happy_falls_back(self):
        """旧五视频配置兼容，已登记但文件缺失的开心素材必须整体回退。"""
        config = json.loads((ROOT / "assets/sprite_config.json").read_text(encoding="utf-8"))
        del config["video"]["clips"]["happy"]
        config["video"]["actions"]["happy"] = "idle"
        with patch("animation.video_player.load_json", return_value=config):
            player = self.player()
        self.wait_for(lambda: player._last_index >= 0)
        player.set_action("happy", force_single_cycle=True)
        self.assertTrue(player.video_enabled)
        self.assertEqual(player.current_action, "idle")
        self.assertEqual(player.action_duration_ms("happy"), 0)
        config["video"]["clips"]["happy"] = {"file": "assets/videos/missing_happy.webm", "frames": 241, "fps": 24}
        config["video"]["actions"]["happy"] = "happy"
        with patch("animation.video_player.load_json", return_value=config):
            other = self.player()
        self.wait_for(lambda: not other.video_enabled)
        self.assertIsNone(other._worker)

    def test_missing_walk_or_invalid_movement_range_falls_back(self):
        """已登记的行走素材缺失或位移帧区间非法时，整体回退旧图集。"""
        for invalid_range in (False, True):
            config = json.loads((ROOT / "assets/sprite_config.json").read_text(encoding="utf-8"))
            clip = config["video"]["clips"]["walking_left"]
            if invalid_range:
                clip["movement_frames"] = [224, 999]
            else:
                clip["file"] = "assets/videos/missing_left.webm"
            with patch("animation.video_player.load_json", return_value=config):
                player = self.player()
            self.wait_for(lambda: not player.video_enabled)
            self.assertIsNone(player._worker)

    def test_frame_callback_switch_cannot_emit_new_action_completion(self):
        """末帧事件回调切换动作后，旧末帧不得结束刚开始的思考。"""
        player = self.player()
        self.wait_for(lambda: player._last_index >= 0)
        player.timer.stop()
        frames = queue.Queue()
        frames.put((268, QImage(240, 320, QImage.Format.Format_RGBA8888)))
        player._worker = types.SimpleNamespace(clip_name="walking_right", frames=frames, eof=True, loop=False)
        player.current_action = "running_right"
        player._last_index = 267
        player._started = time.monotonic() - 12
        completed = []
        player.action_finished.connect(lambda *args: completed.append(args))
        player.frame_presented.connect(lambda *_args: player.set_action("review"))
        player._tick()
        self.assertEqual(player.current_action, "review")
        self.assertFalse(completed)

    def test_stale_error_and_rapid_switch_do_not_replace_new_action(self):
        """快速取消后旧失败信号无效，结束时所有旧线程都已回收。"""
        player = self.player()
        old_serial = player.playback_serial
        for index in range(18):
            player.set_action("review" if index % 2 else "waving")
            self.app.processEvents()
        player.set_action("running")
        player._fail(old_serial, "过期错误")
        self.wait_for(lambda: player._last_index >= 0)
        self.assertTrue(player.video_enabled)
        self.assertEqual(player.current_action, "running")
        processes = [worker._process for _, worker in player._sessions.values() if worker._process]
        self.assertTrue(player.stop())
        self.assertFalse(player.tasks.active_names())
        self.assertTrue(all(process.poll() is not None for process in processes))

    def test_missing_required_clip_falls_back_as_a_whole(self):
        """即使待机存在，只要思考缺失也必须整体使用旧图集。"""
        config = json.loads((ROOT / "assets/sprite_config.json").read_text(encoding="utf-8"))
        config["video"]["clips"]["thinking"]["file"] = "assets/videos/missing.webm"
        with patch("animation.video_player.load_json", return_value=config):
            player = self.player()
        self.wait_for(lambda: not player.video_enabled)
        player.set_action("happy")
        self.assertEqual(player.current_action, "happy")
        self.assertEqual(player.base_size(), (115, 124))

    def test_decoder_unavailable_and_runtime_failure_fall_back(self):
        """解码器缺失和当前播放故障都停止视频并使用旧素材。"""
        with patch("imageio_ffmpeg.get_ffmpeg_exe", side_effect=RuntimeError("missing")):
            player = self.player()
        self.assertFalse(player.video_enabled)
        other = self.player()
        self.wait_for(lambda: other._last_index >= 0)
        failures = []
        other.playback_failed.connect(lambda *args: failures.append(args))
        other._fail(other.playback_serial, "测试解码中断")
        self.assertFalse(other.video_enabled)
        self.assertEqual(len(failures), 1)
        self.assertIsNone(other._worker)

    def test_probe_rejects_missing_alpha(self):
        """能读出 RGBA 并不代表有透明通道，纯不透明帧必须拒绝。"""
        fake_process = types.SimpleNamespace(communicate=lambda timeout: (bytes([255]) * (96 * 128 * 4), None), returncode=0)
        worker = _DecodeWorker(1, "ffmpeg", {"idle": {"path": ROOT / "assets/videos/idle.webm"}}, "idle", (240, 320), True, True)
        with patch.object(worker, "_launch", return_value=fake_process):
            with self.assertRaises(ValueError):
                worker._validate_clips()

    def test_corrupt_video_falls_back(self):
        """必要素材存在但内容损坏时，真实 FFmpeg 校验必须触发整体回退。"""
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp_work") as directory:
            corrupt = Path(directory) / "corrupt.webm"
            corrupt.write_bytes(b"invalid webm")
            config = json.loads((ROOT / "assets/sprite_config.json").read_text(encoding="utf-8"))
            config["video"]["clips"]["waving"]["file"] = str(corrupt)
            with patch("animation.video_player.load_json", return_value=config):
                player = self.player()
            self.wait_for(lambda: not player.video_enabled)
            self.assertIsNone(player._worker)
            self.assertTrue(player.stop())

    def test_high_dpi_size_mask_and_scale_invalidate_old_playback(self):
        """两倍设备密度仍为 240×320，掩码和窗口使用逻辑坐标。"""
        player = self.player()
        self.wait_for(lambda: player._last_index >= 0)
        serial = player.playback_serial
        player.set_device_pixel_ratio(2)
        self.assertGreater(player.playback_serial, serial)
        self.wait_for(lambda: player._last_index >= 0)
        pixmap = player.current_pixmap()
        self.assertEqual((pixmap.width(), pixmap.height()), (480, 640))
        self.assertEqual(pixmap.deviceIndependentSize().toSize().width(), 240)
        region = QRegion(visible_sprite_mask(pixmap))
        self.assertFalse(region.contains(QPoint(0, 0)))
        self.assertTrue(region.contains(QPoint(120, 180)))
        window = QWidget()
        window.sprite_label = QLabel(window)
        window.sprite_label.setPixmap(pixmap)
        window._apply_sprite_window_mask = lambda image: None
        window._sync_floating_widgets = lambda: None
        DesktopPetWindow._resize_for_sprite(window)
        self.assertEqual((window.width(), window.height()), (240, 320))
        window.deleteLater()
        player.set_scale(1.25)
        self.assertEqual(player.base_size(), (300, 400))

    def test_reload_cancels_old_playback(self):
        """重载后旧解码失败与末帧不能干扰新待机。"""
        player = self.player()
        player.set_action("waving")
        serial = player.playback_serial
        player.load()
        player._fail(serial, "旧播放失败")
        self.wait_for(lambda: player._last_index >= 0)
        self.assertTrue(player.video_enabled)
        self.assertEqual(player.current_action, "idle")

    def test_old_completion_cannot_finish_new_owned_action(self):
        """旧结束序号不能覆盖新动作，当前退出结束则走关闭流程。"""
        completed = []
        fake = types.SimpleNamespace(
            _sprite_action_serial=2, _sprite_action_owner="exit", exit_animation_in_progress=True,
            _finalize_exit=lambda: completed.append(True),
        )
        DesktopPetWindow._on_video_action_finished(fake, "waving", 1)
        self.assertFalse(completed)
        DesktopPetWindow._on_video_action_finished(fake, "waving", 2)
        self.assertEqual(completed, [True])

    def test_exit_owns_action_until_waving_finishes(self):
        """退出期间迟到的普通动作请求不能中断挥手。"""
        player = self.player()
        fake = types.SimpleNamespace(sprite_player=player, exit_animation_in_progress=True)
        _set_pet_action(fake, "waving", owner="exit")
        serial = player.playback_serial
        _set_pet_action(fake, "review", owner="late_callback")
        self.assertEqual(player.playback_serial, serial)
        self.assertEqual(fake._sprite_action_owner, "exit")
        self.assertEqual(player.current_action, "waving")

    def test_pending_analysis_keeps_thinking_until_owned_completion(self):
        """截图分析保留思考循环，不能沿用旧单轮参数提前回到待机。"""
        player = self.player()
        fake = types.SimpleNamespace(sprite_player=player)
        _set_pet_action(fake, "review", owner="screenshot", force_single_cycle=True)
        self.assertTrue(player._worker.loop)
        self.assertEqual(fake._sprite_action_owner, "screenshot")
