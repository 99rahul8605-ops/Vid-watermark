"""
Builds ffmpeg filter graphs that make a text or logo watermark "float"
(smoothly drift around) inside the video frame using a Lissajous-style
sine/cosine motion path, then runs ffmpeg while streaming live progress
back to a Telegram status message.
"""

import asyncio
import os
import time

from config import FONT_PATH
from utils.progress import make_bar, human_time


async def get_duration(path: str) -> float:
    """Return media duration in seconds via ffprobe (0 if unknown)."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    out, _ = await proc.communicate()
    try:
        return float(out.decode().strip())
    except Exception:
        return 0.0


def _escape_drawtext(text: str) -> str:
    """Escape characters that are special inside ffmpeg's drawtext filter."""
    text = text.replace("\\", "\\\\")
    text = text.replace(":", "\\:")
    text = text.replace("'", "\u2019")   # smart quote, avoids breaking the filter
    text = text.replace("%", "\\%")
    return text


def build_floating_text_filter(text: str, font_path: str = FONT_PATH,
                                period_x: int = 9, period_y: int = 7,
                                opacity: float = 0.85) -> str:
    """
    Text drifts smoothly around the whole frame following a Lissajous curve
    (different X/Y periods so the path never repeats identically = looks
    "floating" rather than a fixed bounce loop).
    """
    safe_text = _escape_drawtext(text)
    fontfile_part = ""
    if font_path and os.path.exists(font_path):
        fontfile_part = f"fontfile='{font_path}':"

    x_expr = f"(w-text_w)/2+(w-text_w)/2*sin(2*PI*t/{period_x})"
    y_expr = f"(h-text_h)/2+(h-text_h)/2*cos(2*PI*t/{period_y})"

    return (
        f"drawtext={fontfile_part}text='{safe_text}':"
        f"fontcolor=white@{opacity}:fontsize=h*0.045:"
        f"box=1:boxcolor=black@0.35:boxborderw=10:"
        f"x='{x_expr}':y='{y_expr}'"
    )


def build_floating_logo_filters(period_x: int = 9, period_y: int = 7,
                                 logo_width_expr: str = "iw*0.18"):
    """
    Returns (scale_filter, overlay_filter) to be joined with ';' in a
    -filter_complex, floating a logo image (input #1) over the video (#0).
    """
    x_expr = f"(main_w-overlay_w)/2+(main_w-overlay_w)/2*sin(2*PI*t/{period_x})"
    y_expr = f"(main_h-overlay_h)/2+(main_h-overlay_h)/2*cos(2*PI*t/{period_y})"
    scale_filter = f"[1:v]scale={logo_width_expr}:-1,format=rgba,colorchannelmixer=aa=0.85[wm]"
    overlay_filter = f"[0:v][wm]overlay=x='{x_expr}':y='{y_expr}':format=auto"
    return scale_filter, overlay_filter


async def run_ffmpeg_watermark(input_path: str, output_path: str, status_message,
                                text_filter: str | None = None,
                                logo_path: str | None = None,
                                preset: str = "veryfast", crf: int = 23,
                                proc_holder: dict | None = None,
                                cancel_check=None) -> bool:
    """
    Runs ffmpeg to burn a floating watermark into the video, editing
    `status_message` with a live progress bar as it goes.

    Exactly one of `text_filter` (from build_floating_text_filter) or
    `logo_path` should be provided.

    `proc_holder`, if given, is a dict that will be populated with the
    running subprocess under key "proc" so callers can terminate it
    (used to implement /cancel).
    """
    duration = await get_duration(input_path)
    if duration <= 0:
        duration = 1.0

    if logo_path:
        scale_filter, overlay_filter = build_floating_logo_filters()
        filter_complex = f"{scale_filter};{overlay_filter}"
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-i", logo_path,
            "-filter_complex", filter_complex,
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-progress", "pipe:1", "-nostats",
            output_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", text_filter,
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-progress", "pipe:1", "-nostats",
            output_path,
        ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    if proc_holder is not None:
        proc_holder["proc"] = proc

    start = time.time()
    last_edit = 0.0
    out_time_ms = 0

    while True:
        line = await proc.stdout.readline()
        if not line:
            break

        if cancel_check and cancel_check():
            proc.terminate()
            break

        line = line.decode(errors="ignore").strip()

        if line.startswith("out_time_ms="):
            try:
                out_time_ms = int(line.split("=", 1)[1])
            except ValueError:
                pass

        if line.startswith("progress="):
            now = time.time()
            if now - last_edit >= 4 or line == "progress=end":
                current_sec = out_time_ms / 1_000_000
                percent = min(current_sec / duration * 100, 100)
                elapsed = now - start
                speed_factor = current_sec / elapsed if elapsed > 0 else 0
                eta = (duration - current_sec) / speed_factor if speed_factor > 0 else 0
                bar = make_bar(percent)
                text = (
                    f"🎬 **Adding floating watermark...**\n"
                    f"`[{bar}]` {percent:.1f}%\n"
                    f"**Encode speed:** {speed_factor:.2f}x realtime\n"
                    f"**ETA:** {human_time(eta)}   |   **Elapsed:** {human_time(elapsed)}"
                )
                try:
                    await status_message.edit_text(text)
                except Exception:
                    pass
                last_edit = now
            if line == "progress=end":
                break

    await proc.wait()
    return proc.returncode == 0 and os.path.exists(output_path)
