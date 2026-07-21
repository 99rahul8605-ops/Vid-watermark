"""
Very small JSON-file based key/value store for per-user settings
(watermark text, logo path, encode preset, ...).

Not meant for huge scale -- if you need that, swap this module for a
real database (SQLite/Postgres/Redis) while keeping the same function
signatures (get_user / set_user) so the rest of the bot needs no changes.
"""

import json
import os
import threading

from config import DB_FILE

_lock = threading.Lock()


def _ensure_file():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)


def _read_all():
    _ensure_file()
    with open(DB_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def _write_all(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_user(user_id) -> dict:
    with _lock:
        data = _read_all()
    return data.get(str(user_id), {})


def set_user(user_id, key, value):
    with _lock:
        data = _read_all()
        data.setdefault(str(user_id), {})[key] = value
        _write_all(data)


def unset_user(user_id, key):
    with _lock:
        data = _read_all()
        if str(user_id) in data and key in data[str(user_id)]:
            del data[str(user_id)][key]
            _write_all(data)
