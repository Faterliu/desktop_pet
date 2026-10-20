"""校正行走视频色彩与绿边，可参照待机色度，保留原 Alpha 和动作时序。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

import cv2
import imageio_ffmpeg
import numpy as np
from scipy.ndimage import distance_transform_edt, gaussian_filter1d

from make_idle_loop import read_frame

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def stop(process):
    """限时回收本次启动的解码或编码进程，不触碰已有程序。"""
    if process is None:
        return
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)
    for stream in (process.stdin, process.stdout):
        if stream is not None and not stream.closed:
            stream.close()


def color_curve(source, ffmpeg):
    """以中段衣料色度为参考，建立平滑的首尾色彩校正曲线。"""
    result = subprocess.run(
        [ffmpeg, "-v", "error", "-c:v", "libvpx-vp9", "-i", str(source),
         "-vf", "scale=240:320:flags=lanczos", "-pix_fmt", "rgba", "-f", "rawvideo", "-"],
        capture_output=True, check=True, timeout=30,
    )
    frames = np.frombuffer(result.stdout, np.uint8).reshape(-1, 320, 240, 4)
    if len(frames) != 269:
        raise ValueError("本脚本只适配站定保留四帧、共 269 帧的行走定稿")
    colors = np.stack([
        cv2.cvtColor(frame[170:205, 100:140, :3], cv2.COLOR_RGB2LAB)
        .astype(float)[..., 1:].mean(axis=(0, 1)) for frame in frames
    ])
    target = np.median(colors[45:180], axis=0)
    opening = gaussian_filter1d(target - colors[:49], sigma=2, axis=0, mode="nearest")
    fade = np.clip((48 - np.arange(49)) / 18, 0, 1)
    opening *= (fade * fade * (3 - 2 * fade))[:, None]
    curve = np.zeros((269, 2), np.float32)
    curve[:49] = opening
    # 第 231～236 帧是光流过渡，随后倒放开头第 31～0 帧。
    for index in range(231, 237):
        t = (index - 230) / 6
        curve[index] = opening[32] * t * t * (3 - 2 * t)
    for index in range(237, 269):
        curve[index] = opening[268 - index]
    return curve, target - 128


def reference_color_curve(source, reference, ffmpeg):
    """从当前角色裙装提取稳定色度，平滑匹配待机整段的中位参考色。"""
    tracks = []
    for path in (source, reference):
        result = subprocess.run(
            [ffmpeg, "-v", "error", "-threads", "2", "-c:v", "libvpx-vp9", "-i", str(path),
             "-vf", "scale=240:320:flags=lanczos", "-pix_fmt", "rgba", "-f", "rawvideo", "-"],
            capture_output=True, check=True, timeout=40,
        )
        frames = np.frombuffer(result.stdout, np.uint8).reshape(-1, 320, 240, 4)
        colors = []
        for frame in frames:
            # 此区域避开枫叶、裸腿和袜子，仅统计不透明的中暗色衣料。
            part = frame[185:220, 65:180]
            lab = cv2.cvtColor(part[..., :3].astype(np.float32) / 255, cv2.COLOR_RGB2LAB)
            mask = ((part[..., 3] > 250) & (lab[..., 0] > 20) & (lab[..., 0] < 48)
                    & (lab[..., 1] > -6) & (lab[..., 1] < 12)
                    & (lab[..., 2] > 3) & (lab[..., 2] < 30))
            if np.count_nonzero(mask) < 100:
                raise ValueError("缺少足够的裙装参考像素，此构图不能使用当前匹配区域")
            colors.append(np.median(lab[mask, 1:], axis=0))
        if not colors:
            raise ValueError("色彩参考或源视频没有可解码帧")
        tracks.append(np.asarray(colors))
    target = np.median(tracks[1], axis=0)
    curve = gaussian_filter1d(target - tracks[0], sigma=6, axis=0, mode="nearest")
    return curve, target


def correct_frame(frame, delta):
    """调整色度并修复轮廓 RGB，Alpha 保持逐像素不变。"""
    rgb = frame[..., :3].copy()
    alpha = frame[..., 3]
    if np.any(np.abs(delta) > .001):
        original = rgb.astype(np.float32) / 255
        lab = cv2.cvtColor(original, cv2.COLOR_RGB2LAB)
        hsv = cv2.cvtColor(original, cv2.COLOR_RGB2HSV)
        # 保护枫叶等高饱和度橙色，以及眼睛和发丝的深色线条。
        strength = np.clip((.8 - hsv[..., 1]) / .15, 0, 1)
        strength *= np.clip((lab[..., 0] - 6) / 12, 0, 1)
        adjusted = lab.copy()
        adjusted[..., 1:] += delta * strength[..., None]
        baseline = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
        corrected = cv2.cvtColor(adjusted, cv2.COLOR_LAB2RGB)
        rgb = np.rint((original + corrected - baseline) * 255).clip(0, 255).astype(np.uint8)
    signed = rgb.astype(np.int16)
    excess = signed[..., 1] - np.maximum(signed[..., 0], signed[..., 2])
    safe = (alpha >= 250) & (excess <= 3)
    if not np.any(safe):
        raise ValueError("缺少可用于边缘取色的不透明人物像素")
    distance, nearest = distance_transform_edt(~safe, return_indices=True)
    nearest_rgb = rgb[nearest[0], nearest[1]].copy()
    # 小范围绿幕污染使用最近的可靠人物色，远处偏绿像素仅去除多余绿色。
    contaminated = (alpha > 0) & (excess > 5) & (distance <= 6)
    rgb[contaminated] = nearest_rgb[contaminated]
    green = np.maximum(rgb[..., 0], rgb[..., 2])
    rgb[..., 1] = np.minimum(rgb[..., 1], green)
    # 为透明区补十二像素人物延色，减少 4:2:0 编码与缩放时的背景串色。
    transparent = alpha == 0
    rgb[transparent] = 0
    bleed = transparent & (distance <= 12)
    rgb[bleed] = nearest_rgb[bleed]
    return np.dstack((rgb, alpha))


def refine(source, output, left_output=None, reference=None):
    """流式导出修整版，再按需制作同时间轴的水平镜像。"""
    source, output = source.resolve(), output.resolve()
    protected = {source}
    if reference is not None:
        reference = reference.resolve()
        protected.add(reference)
    if output in protected or (left_output is not None and left_output.resolve() in protected | {output}):
        raise ValueError("输出必须使用独立路径，避免覆盖原片")
    capture = cv2.VideoCapture(str(source))
    try:
        if not capture.isOpened() or (int(capture.get(3)), int(capture.get(4))) != (720, 960):
            raise ValueError("输入必须是 720×960 的行走定稿")
        if abs(capture.get(5) - 24) > .01:
            raise ValueError("输入帧率必须为 24 fps")
    finally:
        capture.release()
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    if reference is None:
        curve, target = color_curve(source, ffmpeg)
    else:
        curve, target = reference_color_curve(source, reference, ffmpeg)
    expected_frames = len(curve)
    output.parent.mkdir(parents=True, exist_ok=True)
    decoder = subprocess.Popen(
        [ffmpeg, "-v", "error", "-threads", "2", "-c:v", "libvpx-vp9", "-i", str(source),
         "-pix_fmt", "rgba", "-f", "rawvideo", "-"], stdout=subprocess.PIPE,
    )
    encoder = None
    count = 0
    try:
        encoder = subprocess.Popen(
            [ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "yuva420p", "-s", "720x960",
             "-r", "24", "-i", "-", "-an", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
             "-lossless", "1", "-auto-alt-ref", "0", "-deadline", "good", "-cpu-used", "4", str(output)],
            stdin=subprocess.PIPE,
        )
        for count in range(expected_frames):
            raw = read_frame(decoder.stdout, 720 * 960 * 4)
            if len(raw) != 720 * 960 * 4:
                raise ValueError("视频帧数不足或解码中断")
            frame = np.frombuffer(raw, np.uint8).reshape(960, 720, 4)
            corrected = correct_frame(frame, curve[count])
            # 单独传入原 Alpha 平面，避免 RGBA 自动转换把半透明边缘上取整一档。
            yuv = cv2.cvtColor(corrected[..., :3], cv2.COLOR_RGB2YUV_I420)
            encoder.stdin.write(yuv.tobytes())
            encoder.stdin.write(frame[..., 3].tobytes())
            if (count + 1) % 48 == 0:
                print(f"已修整 {count + 1}/{expected_frames} 帧", flush=True)
        if read_frame(decoder.stdout, 720 * 960 * 4):
            raise ValueError("输入帧数超过色彩分析结果")
        decoder.stdout.close()
        encoder.stdin.close()
        if decoder.wait(timeout=10) or encoder.wait(timeout=30):
            raise RuntimeError("编码或解码失败")
    finally:
        stop(decoder)
        stop(encoder)
    if left_output is not None:
        left_output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-threads", "2", "-c:v", "libvpx-vp9", "-i", str(output),
             "-vf", "hflip", "-an", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-lossless", "1",
             "-auto-alt-ref", "0", "-deadline", "good", "-cpu-used", "4", str(left_output)],
            check=True, timeout=120,
        )
    report = {"source": str(source), "output": str(output), "left_output": str(left_output),
              "frames": expected_frames, "fps": 24, "target_lab_ab": target.tolist(),
              "correction_curve": curve.tolist(), "alpha_modified": False,
              "reference": str(reference) if reference is not None else None,
              "method": "idle_reference_chroma" if reference is not None else "original_269_frame_curve",
              "lightness_modified": False}
    output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成：{output}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--left-output", type=Path)
    parser.add_argument("--reference", type=Path, help="参照当前角色待机的裙装色度；省略时保留原 269 帧定稿模式")
    args = parser.parse_args()
    refine(args.source, args.output, args.left_output, args.reference)
