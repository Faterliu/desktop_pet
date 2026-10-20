"""截取 idle 的相近站姿，并用预乘 Alpha 混合将尾段平滑收回首帧。"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np


def read_frame(stream, size: int) -> bytes:
    """读取完整原始帧，管道提前结束时返回已读数据。"""
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


def blend_rgba(frame: np.ndarray, first: np.ndarray, weight: float) -> np.ndarray:
    """按预乘 Alpha 混合，避免透明区域的残绿污染人物边缘。"""
    current = frame.astype(np.float32)
    target = first.astype(np.float32)
    alpha = current[..., 3:4] * (1 - weight) + target[..., 3:4] * weight
    premultiplied = current[..., :3] * current[..., 3:4] * (1 - weight)
    premultiplied += target[..., :3] * target[..., 3:4] * weight
    rgb = np.divide(premultiplied, alpha, out=np.zeros_like(premultiplied), where=alpha > 0)
    return np.rint(np.concatenate((rgb, alpha), axis=2)).clip(0, 255).astype(np.uint8)


def make_loop(source: Path, output: Path, end_frame: int, blend_frames: int) -> None:
    """保留 [0,end_frame)，仅处理尾部过渡，输出无音轨透明 WebM。"""
    if source.resolve() == output.resolve():
        raise ValueError("输出必须与源文件分开，保留原片")
    capture = cv2.VideoCapture(str(source))
    try:
        if not capture.isOpened():
            raise ValueError("无法打开源视频")
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = capture.get(cv2.CAP_PROP_FPS)
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        capture.release()
    if (width, height) != (720, 960) or abs(fps - 24) > .01:
        raise ValueError("当前流程仅处理 720×960、24 fps 的透明 WebM")
    if not 2 <= blend_frames < end_frame <= total:
        raise ValueError("需要 2 ≤ 过渡帧数 < 截止帧 ≤ 源视频帧数")
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    decoder = subprocess.Popen(
        [ffmpeg, "-v", "error", "-threads", "2", "-c:v", "libvpx-vp9", "-i", str(source),
         "-frames:v", str(end_frame), "-pix_fmt", "rgba", "-f", "rawvideo", "pipe:1"],
        stdout=subprocess.PIPE, creationflags=flags,
    )
    encoder = None
    try:
        encoder = subprocess.Popen(
            [ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
             "-s", f"{width}x{height}", "-r", "24", "-i", "pipe:0", "-an",
             "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-lossless", "1",
             "-auto-alt-ref", "0", "-deadline", "good", "-cpu-used", "4", str(output)],
            stdin=subprocess.PIPE, creationflags=flags,
        )
        first = None
        for index in range(end_frame):
            raw = read_frame(decoder.stdout, width * height * 4)
            if len(raw) != width * height * 4:
                raise RuntimeError("源视频帧数不足或解码中断")
            frame = np.frombuffer(raw, np.uint8).reshape(height, width, 4)
            if first is None:
                first = frame.copy()
                if first[..., 3].min() != 0 or first[..., 3].max() != 255:
                    raise ValueError("源视频必须具有真实透明背景")
            if index >= end_frame - blend_frames:
                t = (index - (end_frame - blend_frames) + 1) / blend_frames
                # 平滑加速与减速，最后一帧严格写回首帧，避免突兀地重置站姿。
                frame = first if t == 1 else blend_rgba(frame, first, t * t * (3 - 2 * t))
            encoder.stdin.write(frame.tobytes())
        encoder.stdin.close()
        decoder.stdout.close()
        if decoder.wait(timeout=10) != 0 or encoder.wait(timeout=30) != 0:
            raise RuntimeError("循环素材编码失败")
    finally:
        for process in (decoder, encoder):
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                if process.stdout and not process.stdout.closed:
                    process.stdout.close()
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
    print(json.dumps({"output": str(output), "frames": end_frame, "fps": 24,
                      "duration_seconds": end_frame / 24, "blend_frames": blend_frames,
                      "output_bytes": output.stat().st_size}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--end-frame", type=int, default=163, help="保留区间 [0,截止帧)，默认 163")
    parser.add_argument("--blend-frames", type=int, default=8, help="尾部平滑回首帧的帧数，默认 8")
    args = parser.parse_args()
    make_loop(args.source, args.output, args.end_frame, args.blend_frames)
