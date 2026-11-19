from __future__ import annotations

import json
import re
import threading
from functools import lru_cache

from app.paths import data_root
from app.store import StoreError, read_json

DATA_DIR = data_root() / "data"
TERMS_FILE = DATA_DIR / "terms.json"

MAX_TERM_LENGTH = 120
MAX_TERMS = 500
_lock = threading.Lock()

_PLACEHOLDER_RE = re.compile(r"§§TERM(\d+)§§")
_cache_token: tuple[int, int] | None = None
_cache_terms: list[str] = []


def _normalize(term: str) -> str:
    return " ".join(term.split()).strip()


@lru_cache(maxsize=MAX_TERMS)
def _boundary_re(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(term)}(?!\w)")


def _parse_terms(raw: object) -> list[str]:
    terms = raw.get("terms", raw) if isinstance(raw, dict) else raw
    if not isinstance(terms, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in terms:
        if not isinstance(item, str):
            continue
        cleaned = _normalize(item)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _remember(terms: list[str]) -> list[str]:
    global _cache_token, _cache_terms
    try:
        stat = TERMS_FILE.stat()
        _cache_token = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        _cache_token = None
    _cache_terms = terms
    return list(terms)


def load_terms() -> list[str]:
    global _cache_token, _cache_terms
    with _lock:
        if not TERMS_FILE.exists():
            _cache_token = None
            _cache_terms = []
            return []
        try:
            stat = TERMS_FILE.stat()
        except OSError:
            return []
        token = (stat.st_mtime_ns, stat.st_size)
        if token == _cache_token:
            return list(_cache_terms)
        try:
            raw = read_json(TERMS_FILE)
        except StoreError:
            return []
        return _remember(_parse_terms(raw))


def _read_terms_for_update() -> list[str]:
    if not TERMS_FILE.exists():
        return []
    return _parse_terms(read_json(TERMS_FILE))


def save_terms(terms: list[str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    unique: list[str] = []
    seen: set[str] = set()
    for item in terms:
        cleaned = _normalize(item)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            unique.append(cleaned)
    payload = json.dumps({"terms": unique}, ensure_ascii=False, indent=2) + "\n"
    temporary = TERMS_FILE.with_suffix(".json.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(TERMS_FILE)
    _remember(unique)


def add_term(term: str) -> list[str]:
    cleaned = _normalize(term)
    if not cleaned:
        raise ValueError("Введите термин.")
    if len(cleaned) > MAX_TERM_LENGTH:
        raise ValueError(f"Термин длиннее {MAX_TERM_LENGTH} знаков.")
    with _lock:
        terms = _read_terms_for_update()
        if cleaned not in terms:
            if len(terms) >= MAX_TERMS:
                raise ValueError(f"В словаре уже {MAX_TERMS} терминов.")
            terms.append(cleaned)
            save_terms(terms)
        else:
            _remember(terms)
        return list(terms)


def remove_term(term: str) -> list[str]:
    cleaned = _normalize(term)
    with _lock:
        terms = [item for item in _read_terms_for_update() if item != cleaned]
        save_terms(terms)
        return terms


def update_term(old: str, new: str) -> list[str]:
    old_cleaned = _normalize(old)
    new_cleaned = _normalize(new)
    if not old_cleaned:
        raise ValueError("Не указан термин для изменения.")
    if not new_cleaned:
        raise ValueError("Введите термин.")
    if len(new_cleaned) > MAX_TERM_LENGTH:
        raise ValueError(f"Термин длиннее {MAX_TERM_LENGTH} знаков.")
    with _lock:
        terms = _read_terms_for_update()
        if old_cleaned not in terms:
            raise ValueError("Термин не найден.")
        if new_cleaned != old_cleaned and new_cleaned in terms:
            raise ValueError("Такой термин уже есть в словаре.")
        terms = [new_cleaned if item == old_cleaned else item for item in terms]
        save_terms(terms)
        return list(terms)


def _ordered_terms(terms: list[str]) -> list[str]:
    return sorted({_normalize(item) for item in terms if _normalize(item)}, key=len, reverse=True)


def matching_terms(text: str, terms: list[str]) -> list[str]:
    """Terms that actually occur in this text, longest first."""
    if not text:
        return []
    found: list[str] = []
    for term in _ordered_terms(terms):
        if _boundary_re(term).search(text):
            found.append(term)
    return found


def protect_terms(text: str, terms: list[str]) -> tuple[str, list[str]]:
    """Replace dictionary terms with placeholders. Longest terms first."""
    mapping: list[str] = []
    protected = text
    for term in _ordered_terms(terms):
        placeholder = f"§§TERM{len(mapping)}§§"
        updated, count = _boundary_re(term).subn(placeholder, protected)
        if not count:
            continue
        protected = updated
        mapping.append(term)
    return protected, mapping


def restore_terms(text: str, mapping: list[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        if 0 <= index < len(mapping):
            return mapping[index]
        return match.group(0)

    return _PLACEHOLDER_RE.sub(replace, text)
