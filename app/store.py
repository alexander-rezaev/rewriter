from __future__ import annotations

import json
from pathlib import Path


class StoreError(Exception):
    """A data file cannot be read, so it must not be overwritten."""


def backup_once(path: Path) -> None:
    copy = Path(str(path) + ".bak")
    if copy.exists():
        return
    try:
        copy.write_bytes(path.read_bytes())
    except OSError:
        return


def read_json(path: Path) -> object:
    """Read JSON. A broken file is copied aside and left in place."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StoreError("Не удалось прочитать файл с данными. Запись остановлена.") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        backup_once(path)
        raise StoreError(
            "Файл с данными повреждён. Запись остановлена, копия сохранена рядом."
        ) from exc
