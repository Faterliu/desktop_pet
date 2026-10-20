"""从外部 WebM 母版导出桌宠有损播放版，逐帧验证后保留加工报告。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw


APP_ROOT = Path(__file__).resolve().parents[1] / "desktop_pet"
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")


def frames(path, ffmpeg):
    """流式解码真实 RGBA，读取中断或取消时限时回收子进程。"""
    process = subprocess.Popen(
        [ffmpeg, "-v", "error", "-threads", "2", "-c:v", "libvpx-vp9", "-i", str(path),
         "-an", "-pix_fmt", "rgba", "-f", "rawvideo", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=FLAGS,
    )
    size = 720 * 960 * 4
    try:
        while True:
            raw = bytearray()
            while len(raw) < size:
                part = process.stdout.read(size - len(raw))
                if not part:
                    break
                raw.extend(part)
            if not raw:
                break
            if len(raw) != size:
                raise ValueError(f"解码尾帧不完整：{path.name}")
            yield np.frombuffer(raw, np.uint8).reshape(960, 720, 4)
        if process.wait(timeout=10):
            raise ValueError(f"视频解码失败：{path.name}")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        process.stdout.close()


def validate(source, output, expected, ffmpeg):
    """核对全片帧数、透明背景、衣服内部和可见像素压缩误差。"""
    original, encoded = frames(source, ffmpeg), frames(output, ffmpeg)
    count = alpha_error = squared_error = visible_count = severe_holes = 0
    worst_interior = 255
    first = last = sample = None
    try:
        while True:
            before, after = next(original, None), next(encoded, None)
            if before is None or after is None:
                if before is not None or after is not None:
                    raise ValueError(f"压缩前后帧数不一致：{output.name}")
                break
            a, b = before[..., 3], after[..., 3]
            if b[0, 0] != 0 or b.min() != 0 or b.max() != 255:
                raise ValueError(f"透明通道异常：{output.name} 第 {count} 帧")
            opaque = (a >= 250).astype(np.uint8)
            interior = cv2.erode(opaque, np.ones((9, 9), np.uint8)).astype(bool)
            if interior.any():
                worst_interior = min(worst_interior, int(b[interior].min()))
                severe_holes += int(np.count_nonzero(b[interior] < 240))
            alpha_error += int(np.abs(a.astype(np.int16) - b.astype(np.int16)).sum())
            visible = opaque.astype(bool)
            delta = before[..., :3][visible].astype(np.float64) - after[..., :3][visible]
            squared_error += float(np.square(delta).sum())
            visible_count += delta.size
            if count == 0:
                first = after.copy()
            last = after.copy()
            if count == expected // 2:
                sample = (before.copy(), after.copy())
            count += 1
    finally:
        original.close()
        encoded.close()
    if count != expected or severe_holes:
        raise ValueError(f"帧数或实体透明度验收失败：{output.name}，帧数 {count}，空洞像素 {severe_holes}")
    mse = squared_error / max(visible_count, 1)
    psnr = 10 * math.log10(255 ** 2 / max(mse, 1e-12))
    if psnr < 35:
        raise ValueError(f"可见区域压缩误差过大：{output.name}，PSNR {psnr:.2f}")
    # 在程序逻辑尺寸检查首尾差异，透明区的隐藏 RGB 不参与判断。
    ends = [cv2.resize(frame.astype(np.float32), (240, 320), interpolation=cv2.INTER_AREA) for frame in (first, last)]
    alpha = [frame[..., 3:4] / 255 for frame in ends]
    seam = max(float(np.abs(ends[0][..., :3] * alpha[0] + bg * (1 - alpha[0])
                            - ends[1][..., :3] * alpha[1] - bg * (1 - alpha[1])).mean()) for bg in (0, 255))
    return {"frames": count, "alpha_mae": alpha_error / (count * 720 * 960),
            "worst_opaque_interior_alpha": worst_interior, "severe_hole_pixels": severe_holes,
            "visible_rgb_psnr_db": psnr, "first_last_composite_mae_240x320": seam}, sample


def compress(source_dir, output_dir, crf):
    """使用外部母版统一编码到独立目录，不覆盖母版或自动替换正式文件。"""
    source_dir, output_dir = source_dir.resolve(), output_dir.resolve()
    if source_dir == output_dir:
        raise ValueError("输出目录必须与源目录分开")
    clips = json.loads((APP_ROOT / "assets/sprite_config.json").read_text(encoding="utf-8"))["video"]["clips"]
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {"encoder": "libvpx-vp9", "crf": crf, "lossless": False,
              "resolution": [720, 960], "fps": 24, "audio": False, "clips": []}
    sheet = Image.new("RGB", (1080, 1040), "#dddddd")
    draw = ImageDraw.Draw(sheet)
    for index, clip in enumerate(clips.values()):
        name = Path(clip["file"]).name
        source, output = source_dir / name, output_dir / name
        if not source.is_file():
            raise FileNotFoundError(source)
        capture = cv2.VideoCapture(str(source))
        try:
            if not capture.isOpened() or (int(capture.get(3)), int(capture.get(4))) != (720, 960):
                raise ValueError(f"源视频规格不符：{name}")
            # WebM 容器时长推算的帧数可能偏一帧，以后面的完整解码计数为准。
            if abs(capture.get(5) - 24) > .01:
                raise ValueError(f"源视频时序不符：{name}")
        finally:
            capture.release()
        print(f"编码 {name}，CRF {crf}", flush=True)
        subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-threads", "2", "-c:v", "libvpx-vp9", "-i", str(source),
             "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", "setsar=1,setpts=N/(24*TB)",
             "-r", "24", "-fps_mode", "cfr", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
             "-lossless", "0", "-crf", str(crf), "-b:v", "0", "-auto-alt-ref", "0",
             "-deadline", "good", "-cpu-used", "2", "-row-mt", "1", "-threads", "4", str(output)],
            check=True, timeout=180, creationflags=FLAGS,
        )
        metrics, sample = validate(source, output, clip["frames"], ffmpeg)
        with source.open("rb") as stream:
            source_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        with output.open("rb") as stream:
            output_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        report["clips"].append({"file": name, "source": str(source), "source_sha256": source_hash,
                                "output_sha256": output_hash, "source_bytes": source.stat().st_size,
                                "output_bytes": output.stat().st_size, **metrics})
        x, y = (index % 3) * 360, (index // 3) * 520
        draw.text((x + 5, y + 5), f"{name}   source / CRF {crf}", fill="black")
        for column, frame in enumerate(sample):
            thumb = Image.fromarray(frame).resize((180, 240), Image.Resampling.LANCZOS)
            for row, background in enumerate(("white", "#202020")):
                panel = Image.new("RGBA", thumb.size, background)
                panel.alpha_composite(thumb)
                sheet.paste(panel.convert("RGB"), (x + column * 180, y + 30 + row * 240))
        (output_dir / "compression_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"通过：{name}，{output.stat().st_size / 1024**2:.2f} MiB，PSNR {metrics['visible_rgb_psnr_db']:.2f} dB", flush=True)
    sheet.save(output_dir / "compression_comparison.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--crf", type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.crf <= 40:
        parser.error("--crf 需要在 1 到 40 之间")
    compress(args.source_dir, args.output_dir, args.crf)
