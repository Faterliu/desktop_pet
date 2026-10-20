"""有界后台解码的透明视频播放器，以及整套图集回退。"""

from __future__ import annotations

import math
import queue
import subprocess
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QImage, QPixmap

from animation.sprite_player import SpritePlayer
from app.background_task_registry import BackgroundTaskRegistry
from storage.json_store import load_json
from utils.logger import get_logger


logger = get_logger(__name__)
WALK_ACTIONS = frozenset({"running_left", "running_right"})


class _DecodeWorker(QObject):
    """只在后台操作子进程和 QImage，通过有界队列交付帧。"""

    finished = Signal()
    failed = Signal(int, str)

    def __init__(self, serial, executable, clips, clip_name, size, loop, validate):
        """保存一次播放所需参数，不在主线程启动解码。"""
        super().__init__()
        self.serial = serial
        self.executable = executable
        self.clips = clips
        self.clip_name = clip_name
        self.size = size
        self.loop = loop
        self.validate = validate
        self.frames: queue.Queue[tuple[int, QImage]] = queue.Queue(maxsize=6)
        self.cancelled = threading.Event()
        self.eof = False
        self._lock = threading.Lock()
        self._process = None

    def stop(self):
        """允许主线程中断管道读取及队列等待，不等待线程退出。"""
        self.cancelled.set()
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                try:
                    self._process.kill()
                except OSError:
                    pass

    def _launch(self, arguments):
        """原子地启动隐藏进程，防止取消后又启动新进程。"""
        with self._lock:
            if self.cancelled.is_set():
                raise InterruptedError()
            self._process = subprocess.Popen(
                [self.executable, "-hide_banner", "-loglevel", "error", "-nostdin",
                 "-filter_threads", "1", "-threads", "2", *arguments],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return self._process

    def _validate_clips(self):
        """逐个验证必要视频可解码且同时具有透明背景与实体区域。"""
        for clip in self.clips.values():
            if not clip["path"].is_file():
                raise ValueError("视频素材缺失")
            process = self._launch([
                "-c:v", "libvpx-vp9", "-i", str(clip["path"]), "-frames:v", "1",
                "-vf", "scale=96:128", "-pix_fmt", "rgba", "-f", "rawvideo", "pipe:1",
            ])
            try:
                raw, _ = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise ValueError("视频验证超时") from None
            if process.returncode or len(raw) != 96 * 128 * 4:
                raise ValueError("视频无法解码")
            alpha = raw[3::4]
            if alpha[0] != 0 or min(alpha) != 0 or max(alpha) != 255:
                raise ValueError("视频缺少有效透明通道")

    @Slot()
    def run(self):
        """连续读取 RGBA 帧，队列满时暂停读取以限制内存。"""
        try:
            if not self.executable:
                raise ValueError("FFmpeg 不可用")
            if self.validate:
                self._validate_clips()
            clip = self.clips[self.clip_name]
            width, height = self.size
            arguments = ["-stream_loop", "-1"] if self.loop else []
            process = self._launch([
                *arguments, "-c:v", "libvpx-vp9", "-i", str(clip["path"]),
                "-an", "-sn", "-vf", f"scale={width}:{height}:flags=lanczos",
                "-pix_fmt", "rgba", "-f", "rawvideo", "pipe:1",
            ])
            frame_bytes = width * height * 4
            index = 0
            while not self.cancelled.is_set():
                raw = bytearray()
                while len(raw) < frame_bytes and not self.cancelled.is_set():
                    chunk = process.stdout.read(frame_bytes - len(raw))
                    if not chunk:
                        break
                    raw.extend(chunk)
                if self.cancelled.is_set():
                    return
                if not raw:
                    break
                if len(raw) != frame_bytes:
                    raise ValueError("视频帧不完整")
                image = QImage(bytes(raw), width, height, width * 4, QImage.Format.Format_RGBA8888).copy()
                while not self.cancelled.is_set():
                    try:
                        self.frames.put((index, image), timeout=0.05)
                        break
                    except queue.Full:
                        continue
                index += 1
            if not self.cancelled.is_set():
                if process.wait(timeout=2) != 0 or self.loop or index != int(clip["frames"]):
                    raise ValueError("视频解码中断或帧数不符")
                self.eof = True
        except Exception as exc:
            if not self.cancelled.is_set():
                reason = str(exc) if isinstance(exc, ValueError) else "视频解码器异常"
                self.failed.emit(self.serial, reason)
        finally:
            self.stop()
            process = self._process
            if process is not None:
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    logger.error("Video decoder did not stop after kill")
                if process.stdout:
                    process.stdout.close()
            self.finished.emit()


class VideoPlayer(QObject):
    """保留逻辑动作接口，默认使用 WebM，失败时整体使用旧播放器。"""

    frame_changed = Signal(QPixmap)
    frame_presented = Signal(str, int, int)
    action_changed = Signal(str)
    action_finished = Signal(str, int)
    playback_failed = Signal(int, str)
    backend_changed = Signal()

    def __init__(self, config_path, scale=1.0, legacy_scale=0.6, enabled=True):
        """准备播放状态，后台验证素材后交付首帧。"""
        super().__init__()
        self.config_path = Path(config_path)
        self.project_root = self.config_path.resolve().parents[1]
        self.scale = self._normal_scale(scale, 1.0)
        self.legacy_scale = self._normal_scale(legacy_scale, 0.6)
        self.enabled = enabled
        self.video_enabled = enabled
        self._failed = False
        self._validated = False
        self._legacy = None
        self._sessions = {}
        self.tasks = BackgroundTaskRegistry()
        self.playback_serial = 0
        self.current_action = "idle"
        self.fallback_action = "idle"
        self.force_single_cycle = False
        self._worker = None
        self._image = QImage()
        self._started = None
        self._last_received = time.monotonic()
        self._last_index = -1
        self._done = False
        self._dpr = 1.0
        self._closed = False
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.load()

    @staticmethod
    def _normal_scale(value, default):
        """配置中的非法缩放回到默认值，不让画布尺寸计算导致启动失败。"""
        try:
            value = float(value)
            return max(0.3, min(3.0, value)) if math.isfinite(value) else default
        except (TypeError, ValueError):
            return default

    def load(self):
        """重载资源配置，使旧播放失效；失败状态在本次运行中保持。"""
        self._cancel_active()
        self._closed = False
        self.config = load_json(self.config_path, {})
        self.scale = self._normal_scale(self.scale, 1.0)
        self.legacy_scale = self._normal_scale(self.legacy_scale, 0.6)
        self.video = self.config.get("video", {})
        try:
            size = self.video.get("display_size", [240, 320])
            if len(size) != 2 or tuple(size) != (240, 320):
                raise ValueError()
            self.clips = {
                name: {**item, "path": self.project_root / item["file"]}
                for name, item in self.video.get("clips", {}).items()
            }
            if any(item["fps"] != 24 or int(item["frames"]) <= 0 for item in self.clips.values()):
                raise ValueError()
            if any(name not in self.clips for name in self.video.get("actions", {}).values()):
                raise ValueError()
            for name in ("walking_left", "walking_right"):
                if name in self.clips:
                    start, end = self.clips[name]["movement_frames"]
                    if not (isinstance(start, int) and isinstance(end, int)
                            and 0 <= start < end < self.clips[name]["frames"]):
                        raise ValueError()
        except (TypeError, ValueError, KeyError, AttributeError):
            self.video = {}
            self.clips = {}
        self._validated = False
        self.video_enabled = self.enabled and not self._failed
        required = {"idle", "thinking", "waving"}
        base_clips = set(self.clips) - {"happy"}
        if self.video_enabled and base_clips not in (required, required | {"walking_left", "walking_right"}):
            self._fail(self.playback_serial, "视频素材配置不完整")
        elif self.video_enabled:
            if self._legacy is not None:
                self._legacy.timer.stop()
            self.set_action("idle")
        else:
            self._use_legacy()

    def _use_legacy(self):
        """只启用一套旧图集，转发其画面和动作信号。"""
        self.video_enabled = False
        if self._legacy is None:
            self._legacy = SpritePlayer(self.config_path, self.legacy_scale)
            self._legacy.frame_changed.connect(self._forward_legacy_frame)
            self._legacy.action_changed.connect(self._forward_legacy_action)
        else:
            self._legacy.scale = self.legacy_scale
            self._legacy.load()
        self.current_action = "idle"
        self.frame_changed.emit(self._legacy.current_pixmap())

    def _forward_legacy_frame(self, pixmap):
        """忽略视频模式或关闭后的旧图集帧。"""
        if not self.video_enabled and not self._closed:
            self.frame_changed.emit(pixmap)

    def _forward_legacy_action(self, action):
        """维持回退播放器的逻辑动作状态。"""
        if not self.video_enabled:
            self.current_action = action
            self.action_changed.emit(action)

    def _cancel_active(self):
        """递增序号并取消所有旧解码，不阻塞主线程。"""
        self.playback_serial += 1
        self.timer.stop()
        for _, worker in list(self._sessions.values()):
            worker.stop()
        self._worker = None

    def _clip_name(self, action):
        """把业务动作映射到新版素材，不改变外部动作名称。"""
        return self.video.get("actions", {}).get(action, "idle")

    def set_action(self, action_name, fallback_action="idle", force_single_cycle=False):
        """循环请求保持进度，显式单轮或不同动作创建新播放。"""
        if self._closed:
            return
        if not self.video_enabled:
            self.playback_serial += 1
            self._legacy.set_action(action_name, fallback_action, force_single_cycle)
            return
        if action_name not in self.config.get("actions", {}):
            action_name = "idle"
        single_requested = force_single_cycle or not self.config.get("actions", {}).get(action_name, {}).get("loop", True)
        if (action_name == "jumping"
            or (action_name == "happy" and self._clip_name(action_name) != "happy")
            or (action_name in WALK_ACTIONS and self.movement_frame_range(action_name) is None)
            or (single_requested and action_name in {"failed", "sleepy", "leaf-hug"})
        ):
            action_name = "idle"
            force_single_cycle = False
        clip_name = self._clip_name(action_name)
        # 输入等待应持续待机，不能因历史单轮参数等待十秒后重置业务状态。
        single = (force_single_cycle and action_name != "waiting") or clip_name in {"waving", "happy"} or action_name in WALK_ACTIONS
        if self._worker is not None and self._worker.loop and self.current_action == action_name and not single and not self._done:
            return
        self._cancel_active()
        self.current_action = action_name
        self.fallback_action = fallback_action
        self.force_single_cycle = single
        self._done = False
        self._started = None
        self._last_index = -1
        self._last_received = time.monotonic()
        try:
            import imageio_ffmpeg
            executable = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError, OSError):
            self._fail(self.playback_serial, "FFmpeg 不可用")
            return
        worker = _DecodeWorker(
            self.playback_serial, executable, self.clips, clip_name,
            self._decode_size(), not single, not self._validated,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(self._fail)
        serial = self.playback_serial
        name = f"video:{serial}"
        self._sessions[serial] = (thread, worker)
        self.tasks.register(name, thread, worker, wait_timeout_ms=1000)
        thread.finished.connect(lambda seq=serial: self._reap(seq))
        self._worker = worker
        thread.start()
        self.timer.start(5)
        self.action_changed.emit(action_name)

    def _reap(self, serial):
        """仅在线程退出后释放注册项，队列中的末帧由播放引用保留。"""
        self._sessions.pop(serial, None)
        self.tasks.unregister(f"video:{serial}")

    @Slot(int, str)
    def _fail(self, serial, reason):
        """只处理当前播放的故障，整体回退并通知窗口。"""
        if serial != self.playback_serial or self._closed:
            return
        logger.warning("Video playback fallback: %s", reason)
        self._failed = True
        self._cancel_active()
        self._use_legacy()
        self.backend_changed.emit()
        self.playback_failed.emit(serial, reason)

    def _tick(self):
        """按实际经过时间取帧，末帧显示足一帧后才发送结束事件。"""
        worker = self._worker
        if worker is None or self._done:
            return
        now = time.monotonic()
        fps = float(self.clips[worker.clip_name]["fps"])
        due = 0 if self._started is None else math.floor((now - self._started) * fps)
        changed = False
        while self._last_index < due:
            try:
                index, image = worker.frames.get_nowait()
            except queue.Empty:
                break
            self._last_index = index
            self._image = image
            self._last_received = now
            changed = True
            if self._started is None:
                self._started = now
                self._validated = True
        if changed:
            # 位移跟随已经显示的媒体帧，解码等待和转身期间不会提前滑动。
            serial = self.playback_serial
            self.frame_presented.emit(self.current_action, serial, self._last_index)
            if serial != self.playback_serial or worker is not self._worker:
                return
            self.frame_changed.emit(self.current_pixmap())
            if serial != self.playback_serial or worker is not self._worker:
                return
        if worker.eof and worker.frames.empty() and self._started is not None and due > self._last_index:
            self._done = True
            self.timer.stop()
            serial = self.playback_serial
            action = self.current_action
            self.action_finished.emit(action, serial)
            # 窗口可在信号中通过动作归属接口处理；独立使用时也能自动回退。
            if serial == self.playback_serial and not self._closed:
                self.set_action(self.fallback_action)
        elif now - self._last_received > (20 if self._started is None else 5):
            self._fail(self.playback_serial, "视频解码超时")

    def current_pixmap(self):
        """返回独立拥有像素存储的高 DPI 画面，空闲首帧前使用透明画布。"""
        if not self.video_enabled and self._legacy is not None:
            return self._legacy.current_pixmap()
        if self._image.isNull():
            pixmap = QPixmap(*self._physical_size())
            pixmap.fill(Qt.GlobalColor.transparent)
        else:
            width, height = self._physical_size()
            image = self._image
            if (image.width(), image.height()) != (width, height):
                image = image.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(self._dpr)
        return pixmap

    def base_size(self):
        """返回逻辑画布尺寸，旧模式继续使用原有缩放。"""
        if not self.video_enabled and self._legacy is not None:
            return self._legacy.base_size()
        size = self.video.get("display_size", [240, 320])
        return max(1, round(size[0] * self.scale)), max(1, round(size[1] * self.scale))

    def _physical_size(self):
        """计算高 DPI 绘制像素数，逻辑尺寸不随设备密度改变。"""
        width, height = self.base_size()
        return max(1, round(width * self._dpr)), max(1, round(height * self._dpr))

    def _decode_size(self):
        """最高解码到正式素材尺寸，放大交给主线程平滑绘制。"""
        width, height = self.base_size()
        ratio = min(self._dpr, 720 / width, 960 / height)
        return max(1, round(width * ratio)), max(1, round(height * ratio))

    def set_scale(self, scale):
        """更新当前后端缩放，视频保留当前画面并重新解码当前动作。"""
        scale = max(0.3, min(3.0, float(scale)))
        if not self.video_enabled:
            self.legacy_scale = scale
            self._legacy.set_scale(scale)
            return
        if self.scale != scale:
            self.scale = scale
            self._restart_current()

    def set_device_pixel_ratio(self, ratio):
        """跨屏幕切换时刷新解码密度，逻辑尺寸保持不变。"""
        ratio = max(1.0, float(ratio))
        if ratio != self._dpr:
            self._dpr = ratio
            if self.video_enabled:
                self._restart_current()

    def _restart_current(self):
        """缩放时取消旧序号，使旧尺寸的帧不能回流。"""
        action, fallback, single = self.current_action, self.fallback_action, self.force_single_cycle
        self._cancel_active()
        self.frame_changed.emit(self.current_pixmap())
        self.set_action(action, fallback, single)

    def action_duration_ms(self, action_name, force_single_cycle=False):
        """返回完整素材时长，不能把循环的一帧间隔当作动作时长。"""
        if not self.video_enabled:
            return self._legacy.action_duration_ms(action_name, force_single_cycle)
        if action_name in {"jumping", "failed", "sleepy", "leaf-hug"} or (
            action_name == "happy" and self._clip_name(action_name) != "happy"
        ) or (
            action_name in WALK_ACTIONS and self.movement_frame_range(action_name) is None
        ):
            return 0
        clip = self.clips[self._clip_name(action_name)]
        return round(1000 * clip["frames"] / clip["fps"])

    def movement_frame_range(self, action_name):
        """返回行走片段的位移起止帧，转身、站定和回正不计入位移。"""
        if not self.video_enabled or action_name not in WALK_ACTIONS:
            return None
        name = self._clip_name(action_name)
        if name not in {"walking_left", "walking_right"}:
            return None
        return tuple(self.clips[name]["movement_frames"])

    @property
    def horizontal_movement_enabled(self):
        """旧图集保留移动能力，视频需要左右两份完整行走素材。"""
        return not self.video_enabled or all(self.movement_frame_range(action) for action in WALK_ACTIONS)

    def stop(self, timeout_ms=1000):
        """限时停止所有解码及图集计时器，未退出线程保留引用供重试。"""
        self._closed = True
        self._cancel_active()
        if self._legacy is not None:
            self._legacy.timer.stop()
        deadline = time.monotonic() + timeout_ms / 1000
        for serial, (thread, _) in list(self._sessions.items()):
            thread.quit()
            if thread.wait(max(0, round((deadline - time.monotonic()) * 1000))):
                self._reap(serial)
        return not self._sessions
