"""
Live progress bar utilities shared by download, upload and ffmpeg stages.
"""

import time

from config import PROGRESS_EDIT_INTERVAL

try:
    from pyrogram.errors import FloodWait
except Exception:  # pragma: no cover - allows utils to be imported standalone
    FloodWait = Exception


def human_size(size) -> str:
    if not size or size < 0:
        return "0 B"
    power = 1024
    n = 0
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size)
    while size >= power and n < len(units) - 1:
        size /= power
        n += 1
    return f"{size:.2f} {units[n]}"


def human_time(seconds) -> str:
    if seconds is None or seconds in (float("inf"), float("-inf")) or seconds < 0:
        return "0s"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def make_bar(percent: float, length: int = 18) -> str:
    percent = max(0, min(100, percent))
    filled = int(length * percent / 100)
    return "█" * filled + "░" * (length - filled)


class ProgressTracker:
    """
    Pass an *instance's* `update` method as the `progress=` callback to
    Pyrogram's download_media / send_video / send_document calls.

    Automatically throttles Telegram message edits (to avoid FloodWait)
    and shows: progress bar, percentage, transferred/total, live speed
    (instantaneous, not just the average) and ETA.
    """

    def __init__(self, message, label: str, emoji: str = "📊",
                 edit_interval: float = PROGRESS_EDIT_INTERVAL,
                 cancel_check=None):
        self.message = message
        self.label = label
        self.emoji = emoji
        self.edit_interval = edit_interval
        self.cancel_check = cancel_check  # optional callable -> bool

        self.start_time = time.time()
        self.last_edit_time = 0.0
        self.last_bytes = 0
        self.last_time = self.start_time

    async def update(self, current: int, total: int):
        # allow cooperative cancellation from /cancel command
        if self.cancel_check and self.cancel_check():
            from pyrogram import StopTransmission
            raise StopTransmission

        now = time.time()
        is_done = total and current >= total
        if not is_done and (now - self.last_edit_time) < self.edit_interval:
            return

        elapsed = now - self.start_time
        delta_bytes = current - self.last_bytes
        delta_time = now - self.last_time
        inst_speed = delta_bytes / delta_time if delta_time > 0 else 0
        avg_speed = current / elapsed if elapsed > 0 else 0
        speed = inst_speed if inst_speed > 0 else avg_speed

        percent = (current / total * 100) if total else 0
        eta = (total - current) / speed if speed > 0 else 0
        bar = make_bar(percent)

        text = (
            f"{self.emoji} **{self.label}**\n"
            f"`[{bar}]` {percent:.1f}%\n"
            f"**Transferred:** {human_size(current)} / {human_size(total)}\n"
            f"**Speed:** {human_size(speed)}/s\n"
            f"**ETA:** {human_time(eta)}   |   **Elapsed:** {human_time(elapsed)}"
        )

        try:
            await self.message.edit_text(text)
        except FloodWait as e:
            time.sleep(e.value)
        except Exception:
            pass

        self.last_edit_time = now
        self.last_bytes = current
        self.last_time = now
