"""解码线程回收、并发上限与失效隔离测试。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from qt_test_app import ensure_app  # noqa: E402

from animation.video_player import MAX_LIVE_SESSIONS, VideoPlayer  # noqa: E402


class _FakeThread:
    """模拟 QThread 的退出状态，可切换是否仍在运行。"""

    def __init__(self, running: bool = False) -> None:
        self.running = running
        self.quit_count = 0
        self.wait_timeouts: list[int] = []

    # 返回当前是否运行。
    def isRunning(self) -> bool:  # noqa: N802
        """返回模拟的运行状态。"""
        return self.running

    # 记录退出请求并标记线程结束。
    def quit(self) -> None:
        """记录一次退出请求。"""
        self.quit_count += 1
        self.running = False

    # 记录等待时长并报告线程已结束。
    def wait(self, timeout_ms: int = 0) -> bool:  # noqa: ARG002
        """记录等待超时并返回已退出。"""
        self.wait_timeouts.append(timeout_ms)
        self.running = False
        return True

    # 保留与 QObject 一致的清理接口。
    def deleteLater(self) -> None:  # noqa: N802
        """模拟对象延迟删除。"""


class _StubbornThread(_FakeThread):
    """模拟已报告退出但状态更新滞后的线程。"""

    # 记录退出请求但不改变运行状态，模拟状态滞后的边界情况。
    def quit(self) -> None:
        """只记录退出请求，不改变运行状态。"""
        self.quit_count += 1

    # 直接报告线程已退出。
    def wait(self, timeout_ms: int = 0) -> bool:
        """报告等待成功。"""
        self.wait_timeouts.append(timeout_ms)
        return True


class _FakeWorker:
    """模拟解码工作对象，只关心是否收到停止请求。"""

    def __init__(self) -> None:
        self.stop_count = 0

    # 记录停止请求次数。
    def stop(self) -> None:
        """记录停止请求。"""
        self.stop_count += 1

    # 保留与 QObject 一致的清理接口。
    def deleteLater(self) -> None:  # noqa: N802
        """模拟对象延迟删除。"""


class _StaleWorker:
    """模拟已过期的解码工作对象，任何取帧都会立刻失败。"""

    @property
    def frames(self):
        """过期对象不应被取帧。"""
        raise AssertionError("stale worker must not be touched")

    # 允许取消流程调用停止。
    def stop(self) -> None:
        """过期对象停止时不做任何事。"""


class VideoSessionLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """准备离屏 Qt 应用，保证信号队列可被处理。"""
        cls.app = ensure_app()

    def setUp(self) -> None:
        """构造关闭视频后端的播放器，避免用例里启动真实解码线程。"""
        self.player = VideoPlayer(ROOT / "assets/sprite_config.json", enabled=False)

    def tearDown(self) -> None:
        """回收播放器，避免旧图集计时器残留。"""
        self.player.stop()
        self.app.processEvents()

    # 向播放器注入一个假的解码会话。
    def add_session(self, serial: int, running: bool = False) -> tuple[_FakeThread, _FakeWorker]:
        """注册一个假会话并返回其线程与工作对象。"""
        thread = _FakeThread(running=running)
        worker = _FakeWorker()
        self.player._sessions[serial] = (thread, worker)
        self.player.tasks.register(f"video:{serial}", thread, worker)
        return thread, worker

    # 线程仍在运行时不能移除会话，否则引用丢失会留下失控线程。
    def test_reap_keeps_running_session(self) -> None:
        """验证运行中的会话被保留。"""
        self.add_session(7, running=True)

        self.player._reap(7)

        self.assertIn(7, self.player._sessions)
        self.assertTrue(self.player.tasks.is_registered("video:7"))

    # 线程退出后应移除会话并清理注册项。
    def test_reap_releases_finished_session(self) -> None:
        """验证已退出会话被回收。"""
        self.add_session(7, running=False)

        self.player._reap(7)

        self.assertNotIn(7, self.player._sessions)
        self.assertFalse(self.player.tasks.is_registered("video:7"))

    # 会话数量超过上限时先回收最旧的线程。
    def test_trim_sessions_caps_live_threads(self) -> None:
        """验证会话数量被限制在上限之内。"""
        for serial in range(MAX_LIVE_SESSIONS + 3):
            self.add_session(serial, running=False)

        self.player._trim_sessions()

        self.assertLessEqual(len(self.player._sessions), MAX_LIVE_SESSIONS)
        self.assertNotIn(0, self.player._sessions)
        self.assertNotIn(1, self.player._sessions)

    # 取消播放应停止所有旧工作对象并清除当前帧来源。
    def test_cancel_active_stops_workers_and_clears_current(self) -> None:
        """验证取消播放的清理结果。"""
        thread, worker = self.add_session(5, running=True)
        self.player._worker = worker
        self.player._worker_serial = 5
        serial_before = self.player.playback_serial

        self.player._cancel_active()

        self.assertIsNone(self.player._worker)
        self.assertIsNone(self.player._worker_serial)
        self.assertEqual(worker.stop_count, 1)
        self.assertEqual(self.player.playback_serial, serial_before + 1)
        self.assertIn(5, self.player._sessions)

    # 序号不匹配时定时器不能读取旧工作对象。
    def test_tick_ignores_stale_worker(self) -> None:
        """验证过期工作对象不会被取帧。"""
        self.player._worker = _StaleWorker()
        self.player._worker_serial = 1
        self.player.playback_serial = 2
        self.player._done = False

        self.player._tick()

    # 解码线程通过信号回到界面线程后再回收。
    def test_session_finished_signal_reaps_session(self) -> None:
        """验证 finished 信号触发界面线程回收。"""
        self.add_session(9, running=False)
        observed: list[int] = []
        self.player._session_finished.connect(observed.append)

        self.player._session_finished.emit(9)
        self.app.processEvents()

        self.assertEqual(observed, [9])
        self.assertNotIn(9, self.player._sessions)
        self.assertFalse(self.player.tasks.is_registered("video:9"))

    # 退出流程以 wait 结果为准，不能因为状态滞后反复重试。
    def test_stop_discards_session_after_wait_reports_finished(self) -> None:
        """验证 stop 在 wait 成功后立即移除会话。"""
        thread = _StubbornThread(running=True)
        worker = _FakeWorker()
        self.player._sessions[11] = (thread, worker)
        self.player.tasks.register("video:11", thread, worker)

        self.assertTrue(self.player.stop(timeout_ms=500))

        self.assertEqual(self.player._sessions, {})


if __name__ == "__main__":
    unittest.main()
