from __future__ import annotations

import re

TABLE_START = "§§TABLE"
TABLE_END = "§§ENDTABLE"
_CELL_BREAK = "\u2028"
_BLOCK_RE = re.compile(rf"{TABLE_START}\n(.*?)\n{TABLE_END}", re.DOTALL)
_TOKEN_RE = re.compile(r"§§TABLE(\d+)§§")


def clean_cell(value: str) -> str:
    text = value or ""
    text = text.replace("\t", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n", _CELL_BREAK).replace("\u200b", "")
    return text.strip()


def format_table(rows: list[list[str]]) -> str:
    width = max((len(row) for row in rows), default=0)
    if width <= 0:
        return ""
    lines = []
    for row in rows:
        cells = [clean_cell(cell) for cell in row]
        if len(cells) < width:
            cells.extend([""] * (width - len(cells)))
        lines.append("\t".join(cells[:width]))
    return f"{TABLE_START}\n" + "\n".join(lines) + f"\n{TABLE_END}"


def protect_tables(text: str) -> tuple[str, list[str]]:
    """Replace table blocks with short markers the model must copy unchanged."""
    mapping: list[str] = []

    def replace(match: re.Match[str]) -> str:
        mapping.append(match.group(0))
        return f"§§TABLE{len(mapping) - 1}§§"

    return _BLOCK_RE.sub(replace, text or ""), mapping


def restore_tables(text: str, mapping: list[str]) -> str:
    """Put original tables back. A marker the model dropped is appended."""
    if not mapping:
        return text or ""
    body = text or ""
    found = {int(item) for item in _TOKEN_RE.findall(body)}

    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        if 0 <= index < len(mapping):
            return mapping[index]
        return match.group(0)

    restored = _TOKEN_RE.sub(replace, body)
    missing = [block for index, block in enumerate(mapping) if index not in found]
    if missing:
        restored = restored.rstrip() + "\n\n" + "\n\n".join(missing)
    return restored
