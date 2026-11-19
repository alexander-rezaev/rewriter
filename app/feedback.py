from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime, timezone

from app.paths import data_root
from app.store import StoreError, read_json

DATA_DIR = data_root() / "data"
FEEDBACK_FILE = DATA_DIR / "feedback.json"

MAX_IDEAS = 200
MAX_TEXT = 1000
MAX_NAME = 80
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean(value: str, limit: int) -> str:
    return " ".join((value or "").split()).strip()[:limit]


def load_ideas() -> list[dict]:
    with _lock:
        try:
            return _read_ideas()
        except StoreError:
            return []


def _read_ideas() -> list[dict]:
    if not FEEDBACK_FILE.exists():
        return []
    raw = read_json(FEEDBACK_FILE)
    ideas = raw.get("ideas") if isinstance(raw, dict) else raw
    if not isinstance(ideas, list):
        return []
    result: list[dict] = []
    for item in ideas:
        if not isinstance(item, dict):
            continue
        text = _clean(str(item.get("text") or ""), MAX_TEXT)
        idea_id = str(item.get("id") or "").strip()
        if not text or not idea_id:
            continue
        likes = item.get("likes") or 0
        result.append(
            {
                "id": idea_id,
                "name": _clean(str(item.get("name") or ""), MAX_NAME),
                "text": text,
                "likes": likes if isinstance(likes, int) and likes > 0 else 0,
                "created": str(item.get("created") or ""),
            }
        )
    return result


def _save(ideas: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"ideas": ideas}, ensure_ascii=False, indent=2) + "\n"
    temporary = FEEDBACK_FILE.with_suffix(".json.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(FEEDBACK_FILE)


def add_idea(name: str, text: str) -> dict:
    cleaned = _clean(text, MAX_TEXT)
    if not cleaned:
        raise ValueError("Напишите идею.")
    with _lock:
        ideas = _read_ideas()
        if len(ideas) >= MAX_IDEAS:
            raise ValueError(f"Уже собрано {MAX_IDEAS} идей.")
        idea = {
            "id": secrets.token_hex(4),
            "name": _clean(name, MAX_NAME),
            "text": cleaned,
            "likes": 0,
            "created": _now(),
        }
        ideas.insert(0, idea)
        _save(ideas)
        return idea


def set_like(idea_id: str, liked: bool) -> dict:
    with _lock:
        ideas = _read_ideas()
        for idea in ideas:
            if idea["id"] != idea_id:
                continue
            idea["likes"] = idea["likes"] + 1 if liked else max(0, idea["likes"] - 1)
            _save(ideas)
            return idea
        raise ValueError("Идея не найдена.")


def delete_idea(idea_id: str) -> None:
    with _lock:
        ideas = _read_ideas()
        kept = [idea for idea in ideas if idea["id"] != idea_id]
        if len(kept) == len(ideas):
            raise ValueError("Идея не найдена.")
        _save(kept)
