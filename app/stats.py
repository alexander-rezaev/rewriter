from __future__ import annotations

import json
import threading

from app.paths import data_root
from app.store import StoreError, backup_once, read_json

DATA_DIR = data_root() / "data"
STATS_FILE = DATA_DIR / "stats.json"
_lock = threading.Lock()


def _empty() -> dict[str, int]:
    return {"rewrites": 0, "likes": 0}


def _read() -> dict[str, int]:
    stats = _empty()
    if not STATS_FILE.exists():
        return stats
    raw = read_json(STATS_FILE)
    if not isinstance(raw, dict):
        backup_once(STATS_FILE)
        raise StoreError("Файл с данными повреждён. Запись остановлена, копия сохранена рядом.")
    for key in stats:
        value = raw.get(key) or 0
        stats[key] = value if isinstance(value, int) and value > 0 else 0
    return stats


def _write(stats: dict[str, int]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(stats, ensure_ascii=False, indent=2) + "\n"
    temporary = STATS_FILE.with_suffix(".json.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(STATS_FILE)


def load_stats() -> dict[str, int]:
    with _lock:
        try:
            return _read()
        except StoreError:
            return _empty()


def add_rewrite() -> dict[str, int]:
    with _lock:
        stats = _read()
        stats["rewrites"] += 1
        _write(stats)
        return stats


def set_app_like(liked: bool) -> dict[str, int]:
    with _lock:
        stats = _read()
        stats["likes"] = stats["likes"] + 1 if liked else max(0, stats["likes"] - 1)
        _write(stats)
        return stats
