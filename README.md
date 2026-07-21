# 🎬 Telegram Floating Watermark Bot

Send a video, get it back with a **smoothly floating** (drifting/bouncing)
watermark burned in — with **live progress bars** (percentage, speed, ETA)
for download, watermark processing and upload.

Built with **Pyrogram** (MTProto, not the plain HTTP Bot API) so transfers
use direct, fast Telegram connections and support files up to **2 GB**
(4 GB for Telegram Premium accounts) instead of the 20 MB `getFile` limit
that plain Bot-API libraries are stuck with.

---

## ✨ Features

- Floating text watermark (Lissajous drift path — never a boring static loop)
- Optional floating **logo/image** watermark instead of text
- Live progress for **download**, **ffmpeg encoding**, and **upload**
  (progress bar, %, speed, ETA, elapsed time)
- `/cancel` to stop a running job mid-way
- Per-user settings (watermark text / logo / encode preset), saved to disk
- Configurable ffmpeg preset to trade off processing speed vs. file size
- Concurrency limit so the server isn't overloaded by multiple users at once

---

## 📁 Project structure

```
telegram_watermark_bot/
├── bot.py                # main bot, all command & message handlers
├── config.py              # reads .env and holds all settings
├── requirements.txt
├── .env.example           # copy to .env and fill in your credentials
├── Procfile                # for Heroku-style process managers
├── Aptfile                 # system packages (ffmpeg, fonts) for buildpacks
├── utils/
│   ├── db.py                # tiny JSON per-user settings store
│   ├── progress.py           # live progress-bar / speed / ETA helper
│   └── watermark.py          # ffmpeg floating-watermark filter builder + runner
├── data/                    # settings.json + saved user logos (auto-created)
├── downloads/               # temp incoming videos (auto-created, auto-cleaned)
└── outputs/                 # temp watermarked videos (auto-created, auto-cleaned)
```

---

## ⚙️ Setup

### 1. System requirements

- Python 3.10+
- **ffmpeg** and **ffprobe** installed and on PATH
  - Debian/Ubuntu: `sudo apt install ffmpeg fonts-dejavu-core`
  - macOS: `brew install ffmpeg`
  - Windows: download from https://ffmpeg.org/download.html and add to PATH

### 2. Get credentials

- `API_ID` and `API_HASH` — from https://my.telegram.org → "API development tools"
- `BOT_TOKEN` — create a bot with [@BotFather](https://t.me/BotFather) on Telegram

### 3. Install & configure

```bash
cd telegram_watermark_bot
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# now edit .env and paste your API_ID / API_HASH / BOT_TOKEN
```

### 4. Run

```bash
python bot.py
```

You should see `Starting Floating Watermark Bot...` in the console.
Open your bot in Telegram and send `/start`.

---

## 🕹️ Usage

| Command | What it does |
|---|---|
| `/start` | Welcome message |
| `/help` | List all commands |
| `/setwatermark <text>` | Set the floating watermark text (default: `@YourBrand`) |
| `/setlogo` | Reply to a photo with this to use a floating **logo** instead of text |
| `/removelogo` | Switch back to text watermark |
| `/preset <name>` | Encode speed: `ultrafast`, `superfast`, `veryfast` (default), `faster`, `fast`, `medium` |
| `/settings` | Show your current watermark/preset configuration |
| `/cancel` | Cancel your currently running download/process/upload |

Then just **send or forward any video** — the bot replies with one message
that live-updates through all three stages:

```
📥 Downloading video
[███████████░░░░░░░] 61.4%
Transferred: 42.10 MB / 68.60 MB
Speed: 3.85 MB/s
ETA: 6s   |   Elapsed: 11s
```

```
🎬 Adding floating watermark...
[██████████████░░░░] 78.2%
Encode speed: 2.10x realtime
ETA: 4s   |   Elapsed: 14s
```

```
📤 Uploading watermarked video
[████████████████░░] 92.0%
Transferred: 63.10 MB / 68.60 MB
Speed: 5.20 MB/s
ETA: 1s   |   Elapsed: 12s
```

---

## 🚀 Speed tuning tips

- `PYROGRAM_WORKERS` in `.env` controls concurrent update handling — raise it
  on a beefier server.
- `/preset ultrafast` gives the fastest ffmpeg processing (bigger output
  file); `medium` gives a smaller/better-quality file but takes longer.
  `veryfast` (default) is a good middle ground.
- `MAX_CONCURRENT_TASKS` limits how many watermark jobs run at once — raise
  it only if your CPU/RAM can handle multiple simultaneous ffmpeg encodes.
- Actual download/upload throughput is ultimately capped by your server's
  network link and Telegram's servers, not by this bot.

---

## 🧩 Notes

- Text watermark uses ffmpeg's `drawtext` filter; logo watermark uses
  `overlay`. Both follow a sine/cosine ("Lissajous") path so the watermark
  drifts smoothly around the whole frame instead of looping a fixed bounce.
- Settings are stored in `data/settings.json`; logos in `data/logos/`.
- Temp files in `downloads/` and `outputs/` are deleted automatically after
  each job (success, failure, or cancel).
- For production, run the bot under a process manager (systemd, pm2,
  Docker, or the included `Procfile` with Heroku/Railway-style platforms —
  remember to also install `ffmpeg` via the `Aptfile`/buildpack).
