"""
Central configuration for the Telegram Floating-Watermark Bot.
All secrets are read from environment variables (see .env.example).
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ---- Telegram credentials -------------------------------------------------
# Get API_ID / API_HASH from https://my.telegram.org  (Api development tools)
# Get BOT_TOKEN from @BotFather
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# ---- Folders ----------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
LOGO_DIR = os.path.join(BASE_DIR, "data", "logos")
DB_FILE = os.path.join(BASE_DIR, "data", "settings.json")

for _d in (DOWNLOAD_DIR, OUTPUT_DIR, LOGO_DIR, os.path.dirname(DB_FILE)):
    os.makedirs(_d, exist_ok=True)

# ---- Watermark defaults -----------------------------------------------------
DEFAULT_WATERMARK_TEXT = os.environ.get("DEFAULT_WATERMARK_TEXT", "@YourBrand")

# A bold system font is required by ffmpeg's drawtext filter.
# Change this if the font is not installed on your system
# (Debian/Ubuntu: `apt install fonts-dejavu-core`)
FONT_PATH = os.environ.get(
    "FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
)

# ---- Performance / speed tuning ---------------------------------------------
# Number of Pyrogram worker threads handling updates concurrently.
PYROGRAM_WORKERS = int(os.environ.get("PYROGRAM_WORKERS", "100"))

# How many watermark jobs can run at the same time (higher = more RAM/CPU used).
MAX_CONCURRENT_TASKS = int(os.environ.get("MAX_CONCURRENT_TASKS", "3"))

# Default ffmpeg encode preset (ultrafast..placebo). Faster preset = quicker
# processing, slightly bigger file. veryfast is a good speed/quality balance.
DEFAULT_PRESET = os.environ.get("DEFAULT_PRESET", "veryfast")
DEFAULT_CRF = int(os.environ.get("DEFAULT_CRF", "23"))

ALLOWED_PRESETS = [
    "ultrafast", "superfast", "veryfast", "faster", "fast", "medium",
]

# How often (seconds) progress messages are edited. Lower = more "live" but
# risks Telegram FloodWait; 3-5s is a safe sweet spot.
PROGRESS_EDIT_INTERVAL = float(os.environ.get("PROGRESS_EDIT_INTERVAL", "4"))
