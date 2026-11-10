"""以小桃的待机肤色校正动作首尾及全片，输出独立的透明 WebM 母版。"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

import cv2
import imageio_ffmpeg
import numpy as np

from make_idle_loop import read_frame
from refine_walking_colors import stop


WIDTH, HEIGHT = 720, 960
PLANE_SIZE = WIDTH * HEIGHT
FRAME_SIZE = PLANE_SIZE * 5 // 2
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
RGB_TO_YUV = np.array(
    [[.257, -.148, .439], [.504, -.291, -.368], [.098, .439, -.071]], np.float32
)
SKIN_BOXES = (
    ((320, 244, 338, 252), (396, 244, 414, 252)),
    ((326, 464, 342, 478), (384, 464, 402, 478)),
    ((318, 740, 336, 774), (394, 740, 412, 774)),
)


def smoothstep(values, low, high):
    """将阈值区间平滑映射到 0～1，避免肤色遮罩出现硬边。"""
    t = np.clip((values - low) / (high - low), 0, 1)
    return t * t * (3 - 2 * t)


def endpoint_frames(path, ffmpeg, count):
    """解码与程序同样的 RGBA，取得正面起止姿势的原始颜色。"""
    select = "eq(n\\,0)" if count == 1 else f"eq(n\\,0)+eq(n\\,{count - 1})"
    result = subprocess.run(
        [ffmpeg, "-v", "error", "-nostdin", "-threads", "2", "-c:v", "libvpx-vp9",
         "-i", str(path), "-an", "-vf", f"select={select}",
         "-fps_mode", "passthrough", "-pix_fmt", "rgba", "-f", "rawvideo", "-"],
        capture_output=True, check=True, timeout=45, creationflags=FLAGS,
    )
    endpoints = np.frombuffer(result.stdout, np.uint8).reshape(-1, HEIGHT, WIDTH, 4)
    if len(endpoints) != min(count, 2):
        raise ValueError(f"无法按给定帧数读取首尾：{path.name}")
    return endpoints


def skin_samples(frame):
    """分别统计脸颊、手背和小腿内部，拒绝明显不符的首尾姿势。"""
    samples = []
    for boxes in SKIN_BOXES:
        rgba = np.concatenate([frame[y0:y1, x0:x1].reshape(-1, 4) for x0, y0, x1, y1 in boxes])
        lab = cv2.cvtColor(rgba[None, :, :3].astype(np.float32) / 255, cv2.COLOR_RGB2LAB)[0]
        plausible = ((rgba[:, 3] >= 250) & (lab[:, 0] > 60) & (lab[:, 1] > 4)
                     & (lab[:, 1] < 29) & (lab[:, 2] > 14) & (lab[:, 2] < 40))
        if np.mean(plausible) < .85:
            raise ValueError("首尾采样区未覆盖足够的皮肤，请确认人物构图和姿势")
        samples.append(np.median(lab[plausible], axis=0))
    return np.stack(samples)


def corrected_frame(raw, corrections):
    """在软遮罩内校色，将差量叠加回原 YUV 平面并保留原 Alpha。"""
    data = np.frombuffer(raw, np.uint8)
    alpha = data[PLANE_SIZE * 3 // 2:].reshape(HEIGHT, WIDTH)
    if alpha[0, 0] != 0 or alpha.max() != 255:
        raise ValueError("帧缺少有效的透明背景或不透明人物")
    points = cv2.findNonZero(alpha)
    x, y, w, h = cv2.boundingRect(points)
    x0, y0 = x // 2 * 2, y // 2 * 2
    x1, y1 = (x + w + 1) // 2 * 2, (y + h + 1) // 2 * 2
    visible = np.s_[y0:y1, x0:x1]
    chroma = np.s_[y0 // 2:y1 // 2, x0 // 2:x1 // 2]
    before_y = data[:PLANE_SIZE].reshape(HEIGHT, WIDTH)[visible]
    before_u = data[PLANE_SIZE:PLANE_SIZE * 5 // 4].reshape(HEIGHT // 2, WIDTH // 2)[chroma]
    before_v = data[PLANE_SIZE * 5 // 4:PLANE_SIZE * 3 // 2].reshape(HEIGHT // 2, WIDTH // 2)[chroma]
    cropped = np.concatenate([plane.ravel() for plane in (before_y, before_u, before_v)])
    rgb = cv2.cvtColor(cropped.reshape((y1 - y0) * 3 // 2, x1 - x0), cv2.COLOR_YUV2RGB_I420)
    lab = cv2.cvtColor(rgb.astype(np.float32) / 255, cv2.COLOR_RGB2LAB)
    light, red, yellow = cv2.split(lab)
    # 皮肤色度介于浅色衣料和橙色枫叶之间，深色头发、眼睛及线条不参与。
    mask = (smoothstep(light, 47, 70) * smoothstep(red, 3, 8)
            * smoothstep(yellow + .45 * red, 20, 25)
            * (1 - smoothstep(red, 29, 41)) * (1 - smoothstep(yellow, 36, 53))
            * smoothstep(alpha[visible].astype(np.float32), 185, 250))
    # 面部、手部和腿部各取自己的偏移，区域之间平滑过渡。
    row = np.arange(y0, y1, dtype=np.float32)[:, None]
    face_to_hands = smoothstep(row, 330, 416)
    hands_to_legs = smoothstep(row, 555, 675)
    face, hands, legs = corrections
    row_shift = face + face_to_hands * (hands - face) + hands_to_legs * (legs - hands)
    changed_lab = lab + row_shift[:, None, :] * mask[..., None]
    rgb_delta = (cv2.cvtColor(changed_lab, cv2.COLOR_LAB2RGB) - cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)) * 255

    # BT.601 限幅差量。色度按 2×2 平均，遮罩外不重新转换原像素。
    delta_y, delta_u, delta_v = cv2.split(rgb_delta @ RGB_TO_YUV)
    size = before_u.shape[::-1]
    out = data.copy()
    for before, delta, plane, region in (
        (before_y, delta_y, out[:PLANE_SIZE].reshape(HEIGHT, WIDTH), visible),
        (before_u, cv2.resize(delta_u, size, interpolation=cv2.INTER_AREA),
         out[PLANE_SIZE:PLANE_SIZE * 5 // 4].reshape(HEIGHT // 2, WIDTH // 2), chroma),
        (before_v, cv2.resize(delta_v, size, interpolation=cv2.INTER_AREA),
         out[PLANE_SIZE * 5 // 4:PLANE_SIZE * 3 // 2].reshape(HEIGHT // 2, WIDTH // 2), chroma),
    ):
        plane[region] = np.clip(before + np.rint(delta), 0, 255).astype(np.uint8)
    return out


def encode(source, targets, count, corrections, crf, ffmpeg):
    """解码和校色一次，按需从同一帧流编码母版和播放版。"""
    decoder = None
    encoder = None
    try:
        decoder = subprocess.Popen(
            [ffmpeg, "-v", "error", "-nostdin", "-threads", "2", "-c:v", "libvpx-vp9", "-i",
             str(source), "-an", "-pix_fmt", "yuva420p", "-f", "rawvideo", "-"],
            stdout=subprocess.PIPE, creationflags=FLAGS,
        )
        arguments = [ffmpeg, "-n", "-v", "error", "-f", "rawvideo", "-pix_fmt", "yuva420p",
                     "-s", f"{WIDTH}x{HEIGHT}", "-r", "24", "-i", "-", "-filter_threads", "1"]
        for i, path in enumerate(targets):
            arguments.extend(
                ["-an", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0",
                 "-lossless", str(int(i == 0)), "-crf", str(crf if i else 0), "-auto-alt-ref", "0",
                 "-deadline", "good", "-cpu-used", "3" if i else "5", "-row-mt", "1",
                 "-threads", "3", str(path)],
            )
        encoder = subprocess.Popen(arguments, stdin=subprocess.PIPE, creationflags=FLAGS)
        for index in range(count):
            raw = read_frame(decoder.stdout, FRAME_SIZE)
            if len(raw) != FRAME_SIZE:
                raise ValueError(f"解码在第 {index} 帧提前结束")
            t = index / (count - 1)
            t = t * t * (3 - 2 * t)
            encoder.stdin.write(corrected_frame(raw, corrections[0] * (1 - t) + corrections[1] * t))
        if read_frame(decoder.stdout, FRAME_SIZE):
            raise ValueError("实际帧数超过给定帧数")
        decoder.stdout.close()
        encoder.stdin.close()
        if decoder.wait(timeout=10) or encoder.wait(timeout=40):
            raise RuntimeError("解码或编码失败")
    finally:
        stop(decoder)
        stop(encoder)


def match(source, reference, output, count, playback=None, crf=20):
    """根据首尾样本计算校色曲线，成功后发布到独立路径。"""
    source, reference, output = (path.resolve() for path in (source, reference, output))
    targets = [output] if playback is None else [output, playback.resolve()]
    if any(path.suffix.lower() != ".webm" for path in targets):
        raise ValueError("输出文件必须使用 .webm 扩展名")
    report = output.with_suffix(".json")
    destinations = [*targets, report]
    if len(set(destinations)) != len(destinations) or {source, reference} & set(destinations):
        raise ValueError("必须用独立路径输出，避免覆盖源文件或参考文件")
    if any(path.exists() for path in destinations):
        raise FileExistsError("输出文件已存在，请使用新目录")
    if count < 2:
        raise ValueError("动作至少需要两帧")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    for path in (source, reference):
        capture = cv2.VideoCapture(str(path))
        try:
            if (int(capture.get(3)), int(capture.get(4))) != (WIDTH, HEIGHT) or abs(capture.get(5) - 24) > .01:
                raise ValueError(f"视频须为 720×960、24 fps：{path.name}")
        finally:
            capture.release()
    target = skin_samples(endpoint_frames(reference, ffmpeg, 1)[0])
    original = np.stack([skin_samples(frame) for frame in endpoint_frames(source, ffmpeg, count)])
    corrections = target - original
    if np.abs(corrections).max() > 10:
        raise ValueError("首尾颜色偏移超出当前角色的校正范围，请先检查采样区")
    result = {
        "frames": count, "source": str(source), "reference": str(reference),
        "target_lab": target.tolist(), "endpoint_shift_lab": corrections.tolist(),
    }
    with ExitStack() as stack:
        staged = []
        for path in targets:
            path.parent.mkdir(parents=True, exist_ok=True)
            directory = stack.enter_context(TemporaryDirectory(prefix=".skin-match-", dir=path.parent))
            staged.append(Path(directory) / path.name)
        encode(source, staged, count, corrections, crf, ffmpeg)
        staged_report = staged[0].with_suffix(".json")
        staged_report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        installed = []
        try:
            for temporary, destination in zip([*staged, staged_report], destinations):
                if destination.exists():
                    raise FileExistsError(destination)
                temporary.rename(destination)
                installed.append(destination)
        except OSError:
            for path in installed:
                path.unlink()
            raise


if __name__ == "__main__":
    cv2.setNumThreads(1)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frames", type=int, required=True)
    parser.add_argument("--playback", type=Path)
    parser.add_argument("--crf", type=int, default=20, choices=range(1, 41))
    args = parser.parse_args()
    match(args.source, args.reference, args.output, args.frames, args.playback, args.crf)
