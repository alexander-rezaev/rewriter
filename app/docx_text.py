from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree

from app.tables import format_table

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_to_text(data: bytes) -> str:
    """Read paragraphs and tables from a .docx. Word markup stays out of the model prompt."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("Нужен файл Word в формате .docx.") from exc
    try:
        xml = archive.read("word/document.xml")
    except KeyError as exc:
        raise ValueError("В файле нет текста документа Word.") from exc
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise ValueError("Файл Word повреждён.") from exc

    body = root.find(_W + "body")
    chunks = _blocks(body if body is not None else root)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(chunks)).strip()
    if not text:
        raise ValueError("В документе нет текста.")
    return text


def _blocks(node: ElementTree.Element) -> list[str]:
    chunks: list[str] = []
    for child in list(node):
        if child.tag == _W + "p":
            chunks.append(_paragraph_text(child).strip())
        elif child.tag == _W + "tbl":
            table = format_table(_table_rows(child))
            if table:
                chunks.append(table)
        elif child.tag == _W + "sdt":
            content = child.find(_W + "sdtContent")
            if content is not None:
                chunks.extend(_blocks(content))
    return chunks


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == _W + "t":
            parts.append(node.text or "")
        elif node.tag == _W + "tab":
            parts.append("\t")
        elif node.tag in {_W + "br", _W + "cr"}:
            parts.append("\n")
    return "".join(parts)


def _table_rows(table: ElementTree.Element) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in list(table):
        if row.tag != _W + "tr":
            continue
        cells: list[str] = []
        for cell in list(row):
            if cell.tag != _W + "tc":
                continue
            cells.append(_cell_text(cell))
            cells.extend([""] * (_span(cell) - 1))
        if any(cell.strip() for cell in cells):
            rows.append(cells)
    return rows


def _span(cell: ElementTree.Element) -> int:
    props = cell.find(_W + "tcPr")
    if props is None:
        return 1
    span = props.find(_W + "gridSpan")
    if span is None:
        return 1
    raw = span.attrib.get(_W + "val", "1")
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def _cell_text(cell: ElementTree.Element) -> str:
    parts: list[str] = []
    for child in list(cell):
        if child.tag == _W + "p":
            parts.append(_paragraph_text(child).strip())
        elif child.tag == _W + "tbl":
            nested = _table_rows(child)
            parts.extend(" | ".join(row) for row in nested)
    return "\u2028".join(part for part in parts if part != "" or len(parts) == 1).strip("\u2028")
