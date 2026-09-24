"""Render an explicitly edited evidence demo from actual UI captures (no browser control).

Requires capego dependencies, a CJK font and ffmpeg (imageio-ffmpeg bundled).
On macOS --voice can add local system speech; otherwise the video has subtitles only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import wave
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont, ImageOps


def wrap(draw, text, font, width):
    lines, line = [], ""
    for char in text:
        if char == "\n" or draw.textlength(line + char, font=font) > width:
            lines.append(line)
            line = "" if char == "\n" else char
        else:
            line += char
    lines += [line] if line else []
    if len(lines) > 1 and len(lines[-1]) < 5:
        lines[-1] = lines[-2][-6:] + lines[-1]
        lines[-2] = lines[-2][:-6]
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--voice", help="Optional installed macOS say voice; generated locally")
    args = parser.parse_args()
    data = json.loads(args.manifest.read_text())
    root = args.manifest.parent
    args.work.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    fonts = {size: ImageFont.truetype(str(args.font), size) for size in [23, 28, 32, 38, 56, 78]}
    clips, cues, sources, elapsed = [], [], [], 0.
    for index, chapter in enumerate(data["chapters"]):
        stem = args.work / f"chapter-{index:02d}"
        canvas = Image.new("RGB", (1920, 1080), "#f2f3ee")
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, 0, 1920, 98), fill="#203c34")
        draw.text((64, 25), "capego", font=fonts[38], fill="white")
        draw.text((315, 34), "软件验证演示  /  SYNTHETIC INPUT", font=fonts[28], fill="#d7e7de")
        draw.text((1590, 37), f"{index+1:02d} / {len(data['chapters']):02d}", font=fonts[23], fill="#d7e7de")
        draw.text((72, 125), chapter["title"], font=fonts[38], fill="#203c34")
        if chapter.get("image"):
            path = root / chapter["image"]
            shot = ImageOps.contain(Image.open(path).convert("RGB"), (1776, 680))
            canvas.paste(shot, ((1920-shot.width)//2, 194+(680-shot.height)//2))
            sources.append({"path": chapter["image"], "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        else:
            for i, line in enumerate(chapter["lines"]):
                y = 270+i*108
                draw.text((114, y), line, font=fonts[56 if i == 0 else 38], fill="#203c34")
        draw.rectangle((0, 897, 1920, 1080), fill="#203c34")
        lines = wrap(draw, chapter["subtitle"], fonts[32], 1740)
        if len(lines) > 3:
            raise ValueError("Subtitle exceeds three lines")
        for i, line in enumerate(lines):
            draw.text((88, 920+i*43), line, font=fonts[32], fill="white")
        draw.text((88, 1047), "实际界面截图剪辑 + 报告展示  ·  模拟数据  ·  非连续录屏", font=fonts[23], fill="#bdcdc4")
        frame = stem.with_suffix(".png")
        canvas.save(frame)
        if index == 0:
            canvas.save(args.output.with_suffix(".jpg"), quality=90)
        duration = chapter.get("seconds", 10)
        audio = stem.with_suffix(".wav")
        if args.voice:
            if not shutil.which("say"):
                raise RuntimeError("--voice requires macOS say")
            speech = stem.with_suffix(".txt")
            speech.write_text(chapter["narration"])
            subprocess.run(["say", "-v", args.voice, "-r", "205", "-f", str(speech), "-o", str(audio),
                            "--file-format=WAVE", "--data-format=LEI16@22050"], check=True)
            with wave.open(str(audio)) as wav:
                duration = max(duration, wav.getnframes()/wav.getframerate()+.8)
        clip = stem.with_suffix(".mp4")
        cmd = [ffmpeg, "-y", "-loglevel", "error", "-loop", "1", "-i", str(frame)]
        if args.voice:
            cmd += ["-i", str(audio), "-af", "apad", "-c:a", "aac", "-b:a", "96k"]
        cmd += ["-t", str(duration), "-r", "24", "-c:v", "libx264", "-preset", "fast", "-tune", "stillimage",
                "-crf", "23", "-pix_fmt", "yuv420p", str(clip)]
        subprocess.run(cmd, check=True)
        clips.append(clip.resolve())
        cues.append({"start": elapsed, "end": elapsed+duration, "title": chapter["title"], "text": chapter["subtitle"]})
        elapsed += duration
        print(f"Rendered {index+1}/{len(data['chapters'])}: {chapter['title']}", flush=True)
    concat = args.work / "concat.txt"
    if any("'" in str(p) for p in clips):
        raise ValueError("Work directory must not contain a single quote")
    concat.write_text("".join(f"file '{p}'\n" for p in clips))
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat),
                    "-c", "copy", "-movflags", "+faststart", str(args.output)], check=True)
    def stamp(seconds):
        ms = round(seconds*1000)
        return f"{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d}.{ms%1000:03d}"
    args.output.with_suffix(".vtt").write_text("WEBVTT\n\n"+"\n\n".join(
        f"{stamp(c['start'])} --> {stamp(c['end'])}\n{c['text']}" for c in cues)+"\n")
    args.output.with_suffix(".json").write_text(json.dumps({"method": data["method"], "chapters": cues,
        "source_images": sources, "voice": args.voice, "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "dimensions": [1920, 1080], "fps": 24}, indent=2, ensure_ascii=False)+"\n")


if __name__ == "__main__":
    main()
