"""使用同目录的 dsh-pet 处理脚本，导出小桃竖版透明视频。"""

from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import cv2
import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw

SOURCE: Path
ACTION = "idle"
SAT_MIN = 0.35
LOSSLESS = False
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def main() -> None:
    """保留源文件，运行原填充和 HSV 抠像函数并验证输出。"""
    capture = cv2.VideoCapture(str(SOURCE))
    if not capture.isOpened():
        raise RuntimeError("无法打开源视频")
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = capture.get(cv2.CAP_PROP_FPS)
    expected_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if (width, height) != (720, 960) or abs(fps - 24) > 0.01 or expected_frames < 1:
        capture.release()
        raise RuntimeError("当前参数仅适用于 720×960、24 fps 的小桃绿幕视频，请先统一素材规格")
    if expected_frames < 24:
        capture.release()
        raise RuntimeError("原抠像脚本每秒抽样背景，请使用至少 1 秒的源视频")
    print(f"源视频：{width}x{height}, {fps:g} fps, {expected_frames} 帧", flush=True)

    ROOT.mkdir(parents=True, exist_ok=True)
    for name in ("video", "step01", "step02", "preview_refined"):
        (ROOT / name).mkdir(exist_ok=True)
    if "--reuse-cleaned" in sys.argv:
        capture.release()
        previous_path = ROOT / "report_refined.json"
        if not previous_path.exists():
            previous_path = ROOT / "report.json"
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
        mask_counts = [previous["mask_max_pixels"]]
        watermark = importlib.import_module("watermark_step01")
        chroma = importlib.import_module("chroma_step02")
        chroma.FFMPEG = FFMPEG
        chroma.W, chroma.H, chroma.FPS = width, height, fps
        cleaned = ROOT / "step01" / SOURCE.name
        if not cleaned.exists():
            raise FileNotFoundError(cleaned)
    else:
        mask_path = ROOT / "video" / f"watermark_mask_{ACTION}.mkv"
        encoder = subprocess.Popen(
            [FFMPEG, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray",
             "-s", f"{width}x{height}", "-r", str(fps), "-i", "-", "-an",
             "-c:v", "ffv1", "-pix_fmt", "gray", str(mask_path)],
            stdin=subprocess.PIPE,
        )
        mask_counts = []
        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                # 只在已核对的角标区域提取浅色文字，不接触人物和枫叶。
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                corners = np.zeros((height, width), dtype=np.uint8)
                corners[:int(height * .12), :int(width * .28)] = 255
                corners[int(height * .90):, int(width * .72):] = 255
                letters = ((hsv[..., 1] < 135) & (hsv[..., 2] > 110)
                           & (corners > 0)).astype(np.uint8) * 255
                mask = cv2.dilate(letters, np.ones((5, 5), np.uint8))
                mask = cv2.bitwise_and(mask, corners)
                mask_counts.append(int(np.count_nonzero(mask)))
                encoder.stdin.write(mask.tobytes())
        finally:
            capture.release()
            encoder.stdin.close()
            if encoder.wait() != 0:
                raise RuntimeError("生成逐帧角标遮罩失败")
        if len(mask_counts) != expected_frames:
            raise RuntimeError("逐帧角标遮罩与源视频帧数不一致")
        print(f"遮罩：{len(mask_counts)} 帧，最多 {max(mask_counts)} 个标记像素", flush=True)

        watermark = importlib.import_module("watermark_step01")
        fill = importlib.import_module("fill_nn")
        chroma = importlib.import_module("chroma_step02")
        # 只覆盖本次进程中的路径和媒体参数，不修改参考仓库文件。
        for module in (watermark, fill, chroma):
            module.FFMPEG = FFMPEG
        for module in (fill, chroma):
            module.W, module.H, module.FPS = width, height, fps
        watermark.OUT = ROOT / "step01"
        watermark.MASK = mask_path
        watermark._is_valid = lambda *args, **kwargs: False
        nearest = fill.kth_nearest
        progress = [0]

        def nearest_with_progress(mask, k):
            """保留原最近邻算法并输出处理进度。"""
            result = nearest(mask, k)
            progress[0] += 1
            if progress[0] % 24 == 0:
                print(f"{ACTION} 水印填充：已处理 {progress[0]} 个有角标帧", flush=True)
            return result

        fill.kth_nearest = nearest_with_progress
        print("运行 watermark_step01._process_one（原 K=5 最近邻填充）", flush=True)
        name, status = watermark._process_one(SOURCE)
        if status != "OK":
            raise RuntimeError(f"水印填充失败：{name} {status}")
        cleaned = ROOT / "step01" / SOURCE.name
    chroma.WIDTH, chroma.HEIGHT = 180, 240
    chroma.MARGIN_X, chroma.MARGIN_Y = 18, 24
    # 原阈值误抠橄榄灰服装；收窄绿色色相并保护低饱和度衣料。
    chroma.GREEN_HUE_MIN = 96.0
    chroma.GREEN_HUE_MAX = 160.0
    chroma.SAT_MIN = SAT_MIN
    color = chroma.sample_background_color(cleaned)
    output = ROOT / "step02" / f"{ACTION}_refined.webm"
    print(f"运行 chroma_step02.convert_video（角色适配 HSV 阈值），背景 {color}", flush=True)
    chroma.convert_video(cleaned, output, color, lossless=LOSSLESS)

    # 显式选择 libvpx 解码，核实实际 Alpha，不能仅凭容器标记判断。
    decoder = subprocess.Popen(
        [FFMPEG, "-v", "error", "-c:v", "libvpx-vp9", "-i", str(output),
         "-an", "-f", "rawvideo", "-pix_fmt", "rgba", "-"], stdout=subprocess.PIPE,
    )
    summary = []
    previews = []
    sample_indices = {n for n in (0, 10, 60, 110, 160, expected_frames - 1) if n < expected_frames}
    montage = Image.new("RGB", (180 * len(sample_indices), 440), "#eeeeee")
    draw = ImageDraw.Draw(montage)
    core_metrics = []
    index = 0
    frame_size = width * height * 4
    try:
        while True:
            raw = chroma.read_exact(decoder.stdout, frame_size)
            if not raw:
                break
            if len(raw) != frame_size:
                raise RuntimeError("透明视频尾帧数据不完整")
            frame = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)
            alpha = frame[..., 3]
            # 此固定区域在全片均位于衣料内部，逐帧检测误抠而非只检查抽样图。
            core = alpha[510:615, 300:420]
            core_metrics.append({"frame": index, "min_alpha": int(core.min()),
                                 "pixels_below_250": int(np.count_nonzero(core < 250))})
            if index in sample_indices:
                image = Image.fromarray(frame)
                image.save(ROOT / "preview_refined" / f"alpha_{index:04d}.png")
                thumb = image.resize((180, 240), Image.Resampling.LANCZOS)
                panel_index = len(summary)
                for row, bg in enumerate(("#ffffff", "#202020")):
                    back = Image.new("RGBA", thumb.size, bg)
                    back.alpha_composite(thumb)
                    back = back.convert("RGB").resize((150, 200), Image.Resampling.LANCZOS)
                    montage.paste(back, (panel_index * 180, 25 + row * 210))
                draw.text((panel_index * 180 + 5, 5), f"{index / fps:.2f}s", fill="black")
                summary.append({"frame": index, "alpha_min": int(alpha.min()),
                                "alpha_max": int(alpha.max()),
                                "transparent_fraction": float(np.mean(alpha == 0)),
                                "partial_fraction": float(np.mean((alpha > 0) & (alpha < 255)))})
            if index % 2 == 0:
                thumb = Image.fromarray(frame).resize((240, 320), Image.Resampling.LANCZOS)
                yy, xx = np.indices((320, 240))
                checker = np.where(((xx // 16 + yy // 16) % 2)[..., None], 224, 248)
                rgb = np.repeat(checker, 3, axis=2).astype(np.uint8)
                back = Image.fromarray(rgb).convert("RGBA")
                back.alpha_composite(thumb)
                previews.append(back.convert("RGB"))
            index += 1
    finally:
        decoder.stdout.close()
        if decoder.wait() != 0:
            raise RuntimeError("透明视频解码失败")
    if index != expected_frames:
        raise RuntimeError(f"输出帧数改变：{index} != {expected_frames}")
    if not all(item["alpha_min"] == 0 and item["alpha_max"] == 255 for item in summary):
        raise RuntimeError("输出缺少真实透明或实体像素")
    if any(item["pixels_below_250"] for item in core_metrics):
        raise RuntimeError("核心衣料区域仍有误抠，需要继续修正阈值")
    montage.save(ROOT / "preview_refined" / "alpha_contact.png")
    # GIF 延时按十毫秒量化，以 80/80/90 毫秒交替逼近 12 fps。
    durations = [80 if n % 3 < 2 else 90 for n in range(len(previews))]
    durations[-1] = round(1000 / fps) if index % 2 else durations[-1]
    gif_path = ROOT / "preview_refined" / f"{ACTION}_checker.gif"
    previews[0].save(gif_path, save_all=True,
                     append_images=previews[1:], duration=durations, loop=0,
                     optimize=False, disposal=2)
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-i", str(gif_path), "-an", "-vf", "fps=24",
         "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         str(ROOT / "preview_refined" / f"{ACTION}_checker.mp4")], check=True,
    )
    report = {"action": ACTION, "source": str(SOURCE), "width": width, "height": height, "fps": fps,
              "frames": index, "duration_seconds": index / fps,
              "output": str(output), "output_bytes": output.stat().st_size,
              "background_sample": color, "mask_max_pixels": max(mask_counts), "lossless": LOSSLESS,
              "alpha_samples": summary,
              "hsv_settings": {"hue_min": chroma.GREEN_HUE_MIN, "hue_max": chroma.GREEN_HUE_MAX,
                               "sat_min": chroma.SAT_MIN, "val_min": chroma.VAL_MIN},
              "core_clothing_check": {"region_xyxy": [300, 510, 420, 615],
                                      "checked_frames": len(core_metrics),
                                      "worst_min_alpha": min(item["min_alpha"] for item in core_metrics),
                                      "total_pixels_below_250": sum(item["pixels_below_250"] for item in core_metrics)},
              "reference_scripts": [str(Path(watermark.__file__)), str(Path(chroma.__file__))],
              "note": "保留原 HSV 算法，调整角色适配阈值；保留完整时长，未裁剪循环。"}
    (ROOT / "report_refined.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="720×960、24 fps 绿幕 MP4")
    parser.add_argument("--action", choices=("idle", "waving", "running", "running_right", "running_left", "happy"), default=ACTION, help="输出动作名；running 表示思考，running_right/running_left 表示左右行走，happy 表示开心")
    parser.add_argument("--work-dir", type=Path, help="独立处理目录，默认 desktop_pet/tmp_work/video_export/动作名")
    parser.add_argument("--reuse-cleaned", action="store_true", help="复用同处理目录的 step01 视频和已有报告，只重新抠像")
    parser.add_argument("--sat-min", type=float, default=SAT_MIN, help="抠绿最低饱和度，默认 0.35；侧身深色头发可尝试 0.5")
    parser.add_argument("--lossless", action="store_true", help="使用 VP9 无损编码，保留细微 Alpha 轮廓，文件体积较大")
    args = parser.parse_args()
    if not 0 <= args.sat_min <= 1:
        parser.error("--sat-min 必须位于 0 到 1 之间")
    SOURCE = args.source.resolve()
    ACTION = args.action
    SAT_MIN = args.sat_min
    LOSSLESS = args.lossless
    ROOT = (args.work_dir or ROOT.parent / "desktop_pet" / "tmp_work" / "video_export" / ACTION).resolve()
    main()
