from __future__ import annotations

import re
from difflib import SequenceMatcher

TOKEN_RE = re.compile(r"\s+|\S+", re.UNICODE)
MARKDOWN_ONLY_RE = re.compile(r"^[\s\-–—*_|`#>+]+$")
ALLOWED_INSERT_CHARS = set(".,;:!?()[] \t—–")
MARKUP_CHARS = set("*_`#|>~")
ELLIPSIS_CHARS = set(".…")
_STRAIGHT_QUOTES = ('"', "“", "”", "„")


def _letters(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _is_punct_or_space(value: str) -> bool:
    return bool(value) and not any(ch.isalnum() for ch in value)


def _strip_markup(value: str) -> str:
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", value)
    cleaned = re.sub(r"__(.+?)__", r"\1", cleaned)
    cleaned = re.sub(r"`(.+?)`", r"\1", cleaned)
    return "".join(ch for ch in cleaned if ch not in MARKUP_CHARS)


def _quote_marks(value: str) -> str:
    return "".join(ch for ch in value if ch in "«»\"“”„")


def _is_markdown_junk(value: str) -> bool:
    stripped = _strip_markup(value).strip()
    if not stripped:
        return True
    return bool(MARKDOWN_ONLY_RE.fullmatch(stripped))


def _is_ellipsis_token(token: str) -> bool:
    stripped = _strip_markup(token).strip()
    if not stripped:
        return False
    return set(stripped) <= ELLIPSIS_CHARS and (len(stripped) >= 2 or "…" in stripped)


def _added_period_after_percent(old: str, new: str) -> bool:
    old_s = old.rstrip()
    new_s = new.rstrip()
    return old_s.endswith("%") and new_s.endswith("%.") and new_s[:-1] == old_s


def _edit_distance(left: str, right: str, max_len_diff: int = 2) -> int:
    if left == right:
        return 0
    if abs(len(left) - len(right)) > max_len_diff:
        return 99
    prev = list(range(len(right) + 1))
    for i, char_left in enumerate(left, 1):
        current = [i]
        for j, char_right in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    prev[j] + 1,
                    prev[j - 1] + (char_left != char_right),
                )
            )
        prev = current
    return prev[-1]


def _common_prefix_len(left: str, right: str) -> int:
    count = 0
    for char_left, char_right in zip(left, right):
        if char_left != char_right:
            break
        count += 1
    return count


def is_inflection(old: str, new: str) -> bool:
    old_letters = _letters(old)
    new_letters = _letters(new)
    if not old_letters or not new_letters or old_letters == new_letters:
        return False
    if min(len(old_letters), len(new_letters)) < 3:
        return False
    prefix = _common_prefix_len(old_letters, new_letters)
    longest = max(len(old_letters), len(new_letters))
    if prefix < 4 or prefix / longest < 0.7:
        return False
    if (len(old_letters) - prefix) > 3 or (len(new_letters) - prefix) > 3:
        return False
    if abs(len(old_letters) - len(new_letters)) > 3:
        return False
    distance = _edit_distance(old_letters, new_letters, max_len_diff=3)
    return distance <= 3


def _is_allowed_insert(token: str, previous: str = "") -> bool:
    token = _strip_markup(token)
    if not token.strip():
        return False
    if _is_markdown_junk(token) or _is_ellipsis_token(token):
        return False
    if not _is_punct_or_space(token):
        return False
    if token.strip() == "." and previous.rstrip().endswith("%"):
        return False
    return all(ch in ALLOWED_INSERT_CHARS for ch in token)


def _is_allowed_edit(old: str, new: str, allow_inflection: bool = False) -> bool:
    new = _strip_markup(new)
    if old == new:
        return True
    if _is_markdown_junk(new):
        return False
    if _is_ellipsis_token(new) and not _is_ellipsis_token(old):
        return False
    if _added_period_after_percent(old, new):
        return False
    if _is_punct_or_space(old) and _is_punct_or_space(new):
        if _is_ellipsis_token(new) and not _is_ellipsis_token(old):
            return False
        return all(ch in ALLOWED_INSERT_CHARS or ch in "—–-" for ch in new)
    old_letters = _letters(old)
    new_letters = _letters(new)
    if old_letters == new_letters:
        return _quote_marks(old) == _quote_marks(new)
    if old_letters and new_letters:
        if allow_inflection and is_inflection(old, new):
            return True
        if abs(len(old_letters) - len(new_letters)) > 2:
            return False
        if _edit_distance(old_letters, new_letters) > 2:
            return False
        return SequenceMatcher(None, old_letters, new_letters).ratio() >= 0.78
    return False


class _Fuzzy:
    def __init__(self, token: str, allow_inflection: bool = False) -> None:
        self.token = token
        self.allow_inflection = allow_inflection

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _Fuzzy):
            return NotImplemented
        return _is_allowed_edit(
            self.token,
            other.token,
            allow_inflection=self.allow_inflection or other.allow_inflection,
        )

    def __hash__(self) -> int:
        return hash(_letters(self.token) or self.token)


def restore_guillemets(source: str, result: str) -> str:
    """Put «ёлочки» back when the model swapped them for straight quotes."""
    source_marks = [ch for ch in source or "" if ch in "«»"]
    if not source_marks:
        return result or ""
    updated = result or ""
    slots = [index for index, ch in enumerate(updated) if ch in "«»\"“”„"]
    if len(slots) == len(source_marks):
        chars = list(updated)
        for index, mark in zip(slots, source_marks):
            chars[index] = mark
        return "".join(chars)
    for inner in re.findall(r"«([^»]*)»", source or ""):
        if not inner.strip():
            continue
        target = f"«{inner}»"
        if target in updated:
            continue
        for left in _STRAIGHT_QUOTES:
            for right in _STRAIGHT_QUOTES:
                candidate = f"{left}{inner}{right}"
                if candidate in updated:
                    updated = updated.replace(candidate, target, 1)
                    break
            else:
                continue
            break
    return updated


def constrain_proofread(
    source: str,
    result: str,
    *,
    allow_inflection: bool = False,
) -> str:
    """Keep original wording; allow spelling, punctuation, and optionally inflections."""
    if not result or result == source:
        return result or source
    src_tokens = TOKEN_RE.findall(source)
    dst_tokens = [_strip_markup(tok) for tok in TOKEN_RE.findall(result)]
    matcher = SequenceMatcher(
        a=[_Fuzzy(tok, allow_inflection) for tok in src_tokens],
        b=[_Fuzzy(tok, allow_inflection) for tok in dst_tokens],
        autojunk=False,
    )
    out: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        src_chunk = src_tokens[i1:i2]
        dst_chunk = dst_tokens[j1:j2]
        if tag == "equal":
            out.extend(dst_chunk)
        elif tag == "delete":
            out.extend(src_chunk)
        elif tag == "insert":
            if i1 == 0:
                continue
            previous = out[-1] if out else ""
            for tok in dst_chunk:
                if _is_allowed_insert(tok, previous):
                    out.append(tok)
                    previous = tok
        elif len(src_chunk) == len(dst_chunk):
            for old, new in zip(src_chunk, dst_chunk):
                out.append(new if _is_allowed_edit(old, new, allow_inflection) else old)
        else:
            out.extend(src_chunk)
    text = _sanitize_punctuation(source, "".join(out).strip())
    return restore_guillemets(source, text) or source


def _sanitize_punctuation(source: str, text: str) -> str:
    if "..." not in source and "…" not in source:
        text = re.sub(r"\.{2,}|…+", "", text)
    if not re.search(r"%\s*\.", source):
        text = re.sub(r"%\s*\.(?=\s|$)", "%", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()
