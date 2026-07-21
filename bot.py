"""
Telegram Floating-Watermark Bot
================================
Send a video -> bot downloads it, burns a smoothly-floating text (or logo)
watermark into it with ffmpeg, and uploads it back -- with a live progress
bar (speed, ETA, %) for every stage: download, encode and upload.

Run:
    python bot.py

Requires ffmpeg + ffprobe installed on the system PATH.
See README.md for full setup instructions.
"""

import asyncio
import logging
import os
import time

# --- Python 3.13+ compatibility shim -----------------------------------
# Pyrogram calls asyncio.get_event_loop() at import time (in pyrogram/sync.py).
# Newer Python versions raise RuntimeError there if no loop already exists
# in the main thread instead of silently creating one. Create it ourselves
# before importing pyrogram so the import succeeds on any Python version.
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())
# -------------------------------------------------------------------------

from pyrogram import Client, StopTransmission, filters
from pyrogram.types import Message

import config
from utils import db
from utils.progress import ProgressTracker, human_size
from utils.watermark import build_floating_text_filter, run_ffmpeg_watermark

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
log = logging.getLogger("watermark-bot")

app = Client(
    "watermark_bot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    workers=config.PYROGRAM_WORKERS,
)

# per-user runtime task state, used for /cancel and to block concurrent
# jobs from the same user: { user_id: {"cancel": bool, "proc": dict} }
TASKS: dict[int, dict] = {}

# global limit on how many ffmpeg jobs run at once across all users
SEMAPHORE = asyncio.Semaphore(config.MAX_CONCURRENT_TASKS)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def user_settings(user_id: int) -> dict:
    s = db.get_user(user_id)
    return {
        "watermark_text": s.get("watermark_text", config.DEFAULT_WATERMARK_TEXT),
        "logo_path": s.get("logo_path"),
        "preset": s.get("preset", config.DEFAULT_PRESET),
        "crf": s.get("crf", config.DEFAULT_CRF),
    }


def cleanup(*paths):
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

@app.on_message(filters.command("start") & filters.private)
async def cmd_start(client, message: Message):
    await message.reply_text(
        "👋 **Welcome to the Floating Watermark Bot!**\n\n"
        "Send me any video and I'll burn a smoothly *floating* watermark "
        "into it, with live progress for download, processing and upload.\n\n"
        "Use /help to see all commands."
    )


@app.on_message(filters.command("help") & filters.private)
async def cmd_help(client, message: Message):
    await message.reply_text(
        "**📖 Commands**\n\n"
        "`/setwatermark <text>` — set the floating watermark text\n"
        "`/setlogo` — reply to a photo with this command to use a floating "
        "logo instead of text\n"
        "`/removelogo` — go back to text watermark\n"
        "`/preset <name>` — encode speed preset: "
        f"{', '.join(config.ALLOWED_PRESETS)}\n"
        "`/crf <18-32>` — output quality/size (lower=bigger&better, higher=smaller)\n"
        "`/settings` — show your current configuration\n"
        "`/cancel` — cancel your current running task\n\n"
        "**How to use:** just send/forward a video file. I'll reply with "
        "live progress bars while downloading, watermarking and uploading."
    )


@app.on_message(filters.command("setwatermark") & filters.private)
async def cmd_setwatermark(client, message: Message):
    if len(message.command) < 2:
        await message.reply_text(
            "Usage: `/setwatermark Your Text Here`", quote=True
        )
        return
    text = message.text.split(None, 1)[1].strip()
    if len(text) > 60:
        await message.reply_text("⚠️ Please keep the watermark under 60 characters.")
        return
    db.set_user(message.from_user.id, "watermark_text", text)
    await message.reply_text(f"✅ Watermark text set to:\n**{text}**")


@app.on_message(filters.command("setlogo") & filters.private)
async def cmd_setlogo(client, message: Message):
    target = message.reply_to_message
    if not target or not target.photo:
        await message.reply_text(
            "⚠️ Reply to a **photo** with `/setlogo` to set it as your "
            "floating logo watermark."
        )
        return
    status = await message.reply_text("⬇️ Saving your logo...")
    logo_path = os.path.join(config.LOGO_DIR, f"{message.from_user.id}.png")
    await client.download_media(target, file_name=logo_path)
    db.set_user(message.from_user.id, "logo_path", logo_path)
    await status.edit_text("✅ Logo saved! It will now float over your videos.")


@app.on_message(filters.command("removelogo") & filters.private)
async def cmd_removelogo(client, message: Message):
    s = user_settings(message.from_user.id)
    cleanup(s["logo_path"])
    db.unset_user(message.from_user.id, "logo_path")
    await message.reply_text("✅ Logo removed. Back to text watermark.")


@app.on_message(filters.command("crf") & filters.private)
async def cmd_crf(client, message: Message):
    if len(message.command) < 2 or not message.command[1].isdigit():
        await message.reply_text(
            "Usage: `/crf <number>` (range 18-32)\n\n"
            "**Lower = better quality, bigger file** (18 ≈ near-lossless)\n"
            "**Higher = smaller file, lower quality** (28-30 ≈ good for weak servers)\n"
            "Default is 23. This matters more for file size than /preset does — "
            "`ultrafast` in particular produces much bigger files unless you "
            "raise the CRF to compensate."
        )
        return
    crf = int(message.command[1])
    if not (18 <= crf <= 32):
        await message.reply_text("⚠️ Please choose a CRF value between 18 and 32.")
        return
    db.set_user(message.from_user.id, "crf", crf)
    await message.reply_text(f"✅ CRF set to `{crf}`.")


@app.on_message(filters.command("preset") & filters.private)
async def cmd_preset(client, message: Message):
    if len(message.command) < 2 or message.command[1].lower() not in config.ALLOWED_PRESETS:
        await message.reply_text(
            "Usage: `/preset name`\nAvailable: " + ", ".join(config.ALLOWED_PRESETS) +
            "\n\n(`ultrafast` = quickest processing, `medium` = smaller/better quality file)"
        )
        return
    preset = message.command[1].lower()
    db.set_user(message.from_user.id, "preset", preset)
    await message.reply_text(f"✅ Encode preset set to `{preset}`.")


@app.on_message(filters.command("settings") & filters.private)
async def cmd_settings(client, message: Message):
    s = user_settings(message.from_user.id)
    logo_state = "✅ set (logo mode)" if s["logo_path"] else "❌ not set (text mode)"
    await message.reply_text(
        "**⚙️ Your settings**\n\n"
        f"**Watermark text:** {s['watermark_text']}\n"
        f"**Logo:** {logo_state}\n"
        f"**Encode preset:** {s['preset']}\n"
        f"**CRF (quality):** {s['crf']}"
    )


@app.on_message(filters.command("cancel") & filters.private)
async def cmd_cancel(client, message: Message):
    uid = message.from_user.id
    task = TASKS.get(uid)
    if not task:
        await message.reply_text("You have no active task to cancel.")
        return
    task["cancel"] = True
    proc = task.get("proc", {}).get("proc")
    if proc and proc.returncode is None:
        proc.terminate()
    await message.reply_text("🛑 Cancelling your current task...")


# --------------------------------------------------------------------------- #
# Core: video -> floating watermark -> video
# --------------------------------------------------------------------------- #

def _is_video_message(_, __, message: Message) -> bool:
    if message.video:
        return True
    if message.document and (message.document.mime_type or "").startswith("video/"):
        return True
    return False


video_filter = filters.create(_is_video_message)


@app.on_message(video_filter & filters.private)
async def handle_video(client, message: Message):
    uid = message.from_user.id

    if uid in TASKS:
        await message.reply_text(
            "⏳ You already have a task running. Use /cancel to stop it first."
        )
        return

    s = user_settings(uid)
    proc_holder: dict = {}
    TASKS[uid] = {"cancel": False, "proc": proc_holder}

    def cancelled():
        return TASKS.get(uid, {}).get("cancel", False)

    status = await message.reply_text("⏳ Queued... waiting for a free slot.", quote=True)

    media = message.video or message.document
    ts = int(time.time())
    in_path = os.path.join(config.DOWNLOAD_DIR, f"{uid}_{ts}_in.mp4")
    out_path = os.path.join(config.OUTPUT_DIR, f"{uid}_{ts}_out.mp4")

    try:
        async with SEMAPHORE:
            if cancelled():
                raise StopTransmission

            # ---- 1. Download with live progress -------------------------
            dl_tracker = ProgressTracker(
                status, "Downloading video", emoji="📥", cancel_check=cancelled
            )
            await client.download_media(message, file_name=in_path, progress=dl_tracker.update)

            if cancelled():
                raise StopTransmission

            # ---- 2. Burn floating watermark with ffmpeg ------------------
            await status.edit_text("🎬 Starting watermark processing...")

            if s["logo_path"] and os.path.exists(s["logo_path"]):
                ok = await run_ffmpeg_watermark(
                    in_path, out_path, status,
                    logo_path=s["logo_path"],
                    preset=s["preset"], crf=s["crf"],
                    proc_holder=proc_holder, cancel_check=cancelled,
                )
            else:
                text_filter = build_floating_text_filter(s["watermark_text"])
                ok = await run_ffmpeg_watermark(
                    in_path, out_path, status,
                    text_filter=text_filter,
                    preset=s["preset"], crf=s["crf"],
                    proc_holder=proc_holder, cancel_check=cancelled,
                )

            if cancelled():
                raise StopTransmission

            if not ok:
                # run_ffmpeg_watermark already logs the real ffmpeg stderr
                # to the console/log file for debugging.
                try:
                    await status.edit_text(
                        "❌ Watermarking failed. Check the bot's terminal/log "
                        "output for the ffmpeg error details, then try again."
                    )
                except Exception:
                    pass
                return

            # ---- 3. Upload with live progress -----------------------------
            ul_tracker = ProgressTracker(
                status, "Uploading watermarked video", emoji="📤", cancel_check=cancelled
            )
            size = os.path.getsize(out_path)
            await client.send_video(
                chat_id=message.chat.id,
                video=out_path,
                caption=f"✅ Done! ({human_size(size)})",
                progress=ul_tracker.update,
                reply_to_message_id=message.id,
                supports_streaming=True,
            )
            await status.edit_text("✅ Finished! Watermarked video sent above.")

    except StopTransmission:
        await status.edit_text("🛑 Task cancelled.")
    except Exception as e:
        log.exception("Error while processing video for user %s", uid)
        try:
            await status.edit_text(f"❌ Something went wrong: `{e}`")
        except Exception:
            pass
    finally:
        cleanup(in_path, out_path)
        TASKS.pop(uid, None)


# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    if not (config.API_ID and config.API_HASH and config.BOT_TOKEN):
        raise SystemExit(
            "Missing API_ID / API_HASH / BOT_TOKEN. Copy .env.example to .env "
            "and fill in your credentials before running the bot."
        )
    log.info("Starting Floating Watermark Bot...")
    app.run()
