from __future__ import annotations

import re

CHUNK_LIMIT = 1400
REWRITE_CHUNK_LIMIT = 3200
CONTEXT_CHARS = 240

_SPLIT_RE = re.compile(r"(?<=[.!?…])(\s+)")
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")
_FACT_RE = re.compile(
    r"«[^»\n]{1,80}»"
    r"|\b\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4}\b"
    r"|\b[A-Za-zА-Яа-яЁё][\w\-]*-\d+\b"
    r"|\b\d[\d\s]{0,14}(?:руб(?:\.|лей|ля)?|%|единиц[аы]?)\b"
    r"|\b\d{2,}\b",
    re.IGNORECASE | re.UNICODE,
)
_SUSPECT_RE = re.compile(
    r"(?<![,;:])\s+(?:что|чтобы|который|которая|которое|которые)\b",
    re.IGNORECASE | re.UNICODE,
)
_LOWER_AFTER_STOP_RE = re.compile(r"[.!?]\s+[а-яё]")
_MIXED_SCRIPT_RE = re.compile(r"[А-Яа-яЁё][A-Za-z]|[A-Za-z][А-Яа-яЁё]")
_TRIPLE_LETTER_RE = re.compile(r"([а-яё])\1\1", re.IGNORECASE)
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+[,:;!?]")
_GLUED_COMMA_RE = re.compile(r"[а-яё],(?=[а-яё])", re.IGNORECASE)
# Wrong forms only. A correct word such as «протокол» must not match.
_TYPO_RE = re.compile(
    r"(?<![а-яё])(?:"
    r"протакол\w*|агенство\w*|колличеств\w*|будующем|вообщем|"
    r"зделал\w*|зделать|извени\w*|"
    r"ихний|ихнего|ихнему|ихним|ихнем|ихняя|ихнее|ихние|ихних"
    r")(?![а-яё])",
    re.IGNORECASE,
)
_ABBR_RE = re.compile(r"(?<![А-Яа-яЁёA-Za-z])[А-ЯЁ]{2,6}(?![А-Яа-яЁёA-Za-z])")
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-]*")
_SHORT_PROOFREAD = 240


def _cut_overflow(text: str, limit: int) -> list[str]:
    """Split a piece that has no sentence boundary, without dropping characters."""
    if len(text) <= limit:
        return [text] if text else []
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + limit)
        if end < len(text):
            window = text[start:end]
            cut = max(window.rfind("\n"), window.rfind(" "))
            if cut >= limit // 2:
                end = start + cut + 1
        if end <= start:
            end = min(len(text), start + limit)
        pieces.append(text[start:end])
        start = end
    return pieces


def _paragraph_pieces(text: str) -> list[str]:
    """Split on line breaks and keep each break with the paragraph above it."""
    parts: list[str] = []
    start = 0
    for match in re.finditer(r"\n", text):
        parts.append(text[start : match.end()])
        start = match.end()
    if start < len(text):
        parts.append(text[start:])
    return [part for part in parts if part]


def _split_sentences(text: str, limit: int) -> list[str]:
    """Pack a paragraph that is longer than one request, without dropping characters."""
    chunks: list[str] = []
    buffer = ""
    for part in _SPLIT_RE.split(text):
        if not part:
            continue
        if len(part) > limit:
            if buffer:
                chunks.append(buffer)
                buffer = ""
            chunks.extend(_cut_overflow(part, limit))
            continue
        if buffer and len(buffer) + len(part) > limit:
            chunks.append(buffer)
            buffer = part
        else:
            buffer += part
    if buffer:
        chunks.append(buffer)
    return chunks or [text]


def split_chunks(text: str, limit: int = CHUNK_LIMIT) -> list[str]:
    """Pack whole paragraphs. A paragraph longer than the limit is split by sentences."""
    if len(text) <= limit:
        return [text]
    paragraphs = _paragraph_pieces(text)
    if len(paragraphs) <= 1:
        return _split_sentences(text, limit)
    chunks: list[str] = []
    buffer = ""
    for part in paragraphs:
        if len(part) > limit:
            if buffer:
                chunks.append(buffer)
                buffer = ""
            chunks.extend(_split_sentences(part, limit))
            continue
        if buffer and len(buffer) + len(part) > limit:
            chunks.append(buffer)
            buffer = part
        else:
            buffer += part
    if buffer:
        chunks.append(buffer)
    return chunks or [text]


def context_tail(text: str, limit: int = CONTEXT_CHARS) -> str:
    """Keep the last one or two sentences of the previous request."""
    compact = (text or "").strip()
    if not compact:
        return ""
    sentences = [part.strip() for part in _SENTENCE_RE.split(compact) if part.strip()]
    tail = " ".join(sentences[-2:]) if len(sentences) >= 2 else compact
    if len(tail) <= limit:
        return tail
    window = tail[-limit:]
    for mark in ("\n", ". ", "! ", "? ", "… "):
        pos = window.find(mark)
        if 0 <= pos <= limit // 2:
            window = window[pos + len(mark) :]
            break
    return window.strip()


def _remember(found: list[str], seen: set[str], token: str, limit: int) -> bool:
    token = " ".join(token.split())
    key = token.casefold()
    if len(token) < 2 or key in seen:
        return len(found) < limit
    seen.add(key)
    found.append(token)
    return len(found) < limit


def _title_word(word: str) -> bool:
    parts = [part for part in word.split("-") if part]
    if not parts:
        return False
    for part in parts:
        if not part[:1].isupper() or not any(char.islower() for char in part[1:]):
            return False
    return True


def _name_spans(text: str) -> list[str]:
    """Two or more capitalized words in a row. One word, even at the start, is not a name."""
    matches = list(_WORD_RE.finditer(text))
    names: list[str] = []
    run: list[str] = []
    previous = 0

    def flush() -> None:
        if len(run) >= 2:
            names.append(" ".join(run))
        run.clear()

    for match in matches:
        word = match.group(0)
        if not _title_word(word):
            flush()
            previous = match.end()
            continue
        gap = text[previous:match.start()]
        if run and gap.strip():
            flush()
        run.append(word)
        previous = match.end()
    flush()
    return names


def extract_facts(text: str, limit: int = 30) -> list[str]:
    """Numbers, dates, codes, abbreviations and names that the rewrite must keep."""
    found: list[str] = []
    seen: set[str] = set()
    source = text or ""
    for match in _FACT_RE.finditer(source):
        if not _remember(found, seen, match.group(0), limit):
            return found
    for match in _ABBR_RE.finditer(source):
        if not _remember(found, seen, match.group(0), limit):
            return found
    for name in _name_spans(source):
        if not _remember(found, seen, name, limit):
            return found
    return found


def should_proofread_chunk(text: str) -> bool:
    """Send a short single sentence even when no known error pattern matches."""
    if likely_has_errors(text):
        return True
    stripped = (text or "").strip()
    if not stripped or len(stripped) > _SHORT_PROOFREAD:
        return False
    endings = len(re.findall(r"[.!?…]+", stripped))
    return endings <= 1


def likely_has_errors(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if _SUSPECT_RE.search(stripped):
        return True
    if len(stripped) >= 40 and stripped[-1] not in ".!?…":
        return True
    if _LOWER_AFTER_STOP_RE.search(stripped):
        return True
    if _MIXED_SCRIPT_RE.search(stripped) or _TRIPLE_LETTER_RE.search(stripped):
        return True
    if _SPACE_BEFORE_PUNCT_RE.search(stripped) or _GLUED_COMMA_RE.search(stripped):
        return True
    if _TYPO_RE.search(stripped):
        return True
    return False


def should_retry(source: str, corrected: str, model_changed: bool) -> bool:
    """Retry only when the text came back unchanged and still looks wrong."""
    if " ".join(source.split()) != " ".join(corrected.split()):
        return False
    return model_changed or likely_has_errors(source)
