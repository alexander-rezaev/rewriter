from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.proofread_guard import is_inflection

LETTER_RE = re.compile(r"[^\W_]", re.UNICODE)
TOKEN_RE = re.compile(r"\s+|\S+", re.UNICODE)


def _merge(segments: list[dict[str, str | None]]) -> list[dict[str, str | None]]:
    merged: list[dict[str, str | None]] = []
    for seg in segments:
        text = seg.get("text") or ""
        if not text:
            continue
        if merged and merged[-1]["kind"] == seg["kind"]:
            merged[-1]["text"] = (merged[-1]["text"] or "") + text
        else:
            merged.append({"text": text, "kind": seg["kind"]})
    return merged


def highlight_rewrite(source: str, result: str) -> list[dict[str, str | None]]:
    src_tokens = TOKEN_RE.findall(source)
    dst_tokens = TOKEN_RE.findall(result)
    matcher = SequenceMatcher(a=src_tokens, b=dst_tokens, autojunk=False)
    segments: list[dict[str, str | None]] = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        chunk = "".join(dst_tokens[j1:j2])
        if not chunk:
            continue
        if tag == "equal":
            segments.append({"text": chunk, "kind": None})
        else:
            kind = "change" if chunk.strip() else None
            segments.append({"text": chunk, "kind": kind})
    return _merge(segments)


def _is_letter_at(text: str, index: int) -> bool:
    if index < 0 or index >= len(text):
        return False
    return bool(LETTER_RE.match(text[index]))


def _word_at(text: str, index: int) -> str:
    if index < 0:
        index = 0
    if index >= len(text):
        return ""
    start = index
    while start > 0 and LETTER_RE.match(text[start - 1]):
        start -= 1
    end = index
    while end < len(text) and LETTER_RE.match(text[end]):
        end += 1
    return text[start:end]


def _comma_was_removed(old: str, new: str) -> bool:
    """A comma disappeared and the letters around it stayed the same."""
    if old.count(",") <= new.count(","):
        return False
    old_letters = "".join(LETTER_RE.findall(old))
    new_letters = "".join(LETTER_RE.findall(new))
    return old_letters == new_letters


def _mark_removed_comma(kinds: list[str | None], result: str, index: int) -> None:
    """Underline the space where a comma used to be. Do not color the letters."""
    if not result:
        return
    cursor = index - 1
    while cursor >= 0 and result[cursor].isspace():
        if kinds[cursor] is None:
            kinds[cursor] = "punctuation"
        cursor -= 1
    cursor = index
    while cursor < len(result) and result[cursor].isspace():
        if kinds[cursor] is None:
            kinds[cursor] = "punctuation"
        cursor += 1


def _segments_from_kinds(result: str, kinds: list[str | None]) -> list[dict[str, str | None]]:
    if not result:
        return []
    segments: list[dict[str, str | None]] = []
    start = 0
    for index in range(1, len(result) + 1):
        if index == len(result) or kinds[index] != kinds[start]:
            segments.append({"text": result[start:index], "kind": kinds[start]})
            start = index
    return _merge(segments)


def _proofread_kind(
    old: str,
    new: str,
    source: str,
    result: str,
    i1: int,
    j1: int,
    j2: int,
    *,
    grammar: bool = False,
) -> str:
    if _comma_was_removed(old, new):
        return "punctuation"
    glue = r"[\s\-‑–—]+"
    if re.fullmatch(glue, new or "") or re.fullmatch(glue, old or ""):
        if _is_letter_at(result, j1 - 1) and _is_letter_at(result, j2):
            return "spelling"
        if _is_letter_at(source, i1 - 1) and _is_letter_at(source, i1 + len(old)):
            return "spelling"
    sample = old + new
    if not LETTER_RE.search(sample):
        return "punctuation"
    old_letters = "".join(LETTER_RE.findall(old))
    new_letters = "".join(LETTER_RE.findall(new))
    if old_letters != new_letters:
        if grammar:
            old_word = _word_at(source, i1) or old
            new_word = _word_at(result, j1) or new
            if is_inflection(old_word, new_word):
                return "grammar"
        return "spelling"
    rest = LETTER_RE.sub("", old) + LETTER_RE.sub("", new)
    if re.fullmatch(r"[\s\-‑–—]*", rest or ""):
        return "spelling"
    return "punctuation"


def _expand_spelling_to_words(result: str, segments: list[dict[str, str | None]]) -> list[dict[str, str | None]]:
    if not result or not segments:
        return segments
    kinds: list[str | None] = []
    for seg in segments:
        kinds.extend([seg["kind"]] * len(seg["text"] or ""))
    if len(kinds) != len(result):
        return segments
    i = 0
    n = len(result)
    while i < n:
        if kinds[i] in {"spelling", "grammar"}:
            kind = kinds[i]
            start = i
            while start > 0 and LETTER_RE.match(result[start - 1]):
                start -= 1
            end = i + 1
            while end < n and LETTER_RE.match(result[end]):
                end += 1
            for j in range(start, end):
                kinds[j] = kind
            i = end
        else:
            i += 1
    rebuilt: list[dict[str, str | None]] = []
    start = 0
    for i in range(1, n + 1):
        if i == n or kinds[i] != kinds[start]:
            rebuilt.append({"text": result[start:i], "kind": kinds[start]})
            start = i
    return _merge(rebuilt)


def highlight_proofread(
    source: str,
    result: str,
    uncertain: list[str] | None = None,
    *,
    grammar: bool = False,
) -> list[dict[str, str | None]]:
    kinds: list[str | None] = [None] * len(result)
    matcher = SequenceMatcher(a=source, b=result, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old = source[i1:i2]
        new = result[j1:j2]
        if new:
            kind = _proofread_kind(old, new, source, result, i1, j1, j2, grammar=grammar)
            for index in range(j1, j2):
                kinds[index] = kind
        if _comma_was_removed(old, new):
            _mark_removed_comma(kinds, result, j1)
    marked = _expand_spelling_to_words(result, _segments_from_kinds(result, kinds))
    return _apply_uncertain(result, marked, uncertain or [])


def _apply_uncertain(
    result: str,
    segments: list[dict[str, str | None]],
    uncertain: list[str],
) -> list[dict[str, str | None]]:
    if not result or not uncertain:
        return segments
    kinds: list[str | None] = []
    for seg in segments:
        kinds.extend([seg["kind"]] * len(seg["text"] or ""))
    if len(kinds) != len(result):
        return segments
    for raw in uncertain:
        word = raw.strip().strip(".,;:!?…")
        if len(word) < 2:
            continue
        pattern = re.compile(rf"(?<!\w){re.escape(word)}(?!\w)", re.IGNORECASE | re.UNICODE)
        for match in pattern.finditer(result):
            start, end = match.start(), match.end()
            if any(kinds[i] in {"spelling", "punctuation", "grammar"} for i in range(start, end)):
                continue
            while start > 0 and LETTER_RE.match(result[start - 1]):
                start -= 1
            while end < len(result) and LETTER_RE.match(result[end]):
                end += 1
            for index in range(start, end):
                if kinds[index] is None:
                    kinds[index] = "uncertain"
    rebuilt: list[dict[str, str | None]] = []
    start = 0
    for i in range(1, len(result) + 1):
        if i == len(result) or kinds[i] != kinds[start]:
            rebuilt.append({"text": result[start:i], "kind": kinds[start]})
            start = i
    return _merge(rebuilt)
