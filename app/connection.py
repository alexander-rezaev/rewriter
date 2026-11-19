from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ADDRESS = "http://127.0.0.1:11434"
DEFAULT_MODEL = "t-tech/T-lite-it-2.1:q4_K_M"
DEFAULT_TEXT = """# Адрес Ollama. Сменили сервер — поправьте address и запустите Rewriter.exe снова.
address=http://127.0.0.1:11434
model=t-tech/T-lite-it-2.1:q4_K_M
port=8181
"""


def parse_connection(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key and value:
            values[key] = value
    return values


def apply_connection(path: Path) -> int:
    """Read ollama.txt and point this process at that Ollama server."""
    if not path.is_file():
        path.write_text(DEFAULT_TEXT, encoding="utf-8")
    values = parse_connection(path.read_text(encoding="utf-8-sig"))
    address = values.get("address") or values.get("ollama") or values.get("url") or DEFAULT_ADDRESS
    if "://" not in address:
        address = "http://" + address.lstrip("/")
    model = values.get("model") or DEFAULT_MODEL
    os.environ["LLM_BACKEND"] = "ollama"
    os.environ["LLM_BASE_URL"] = address
    os.environ["LLM_MODEL"] = model
    os.environ["LLM_REWRITE_MODEL"] = values.get("rewrite") or model
    os.environ["LLM_PROOFREAD_MODEL"] = values.get("proofread") or model
    os.environ["LLM_TIMEOUT"] = values.get("timeout") or "600"
    os.environ["LLM_TEMPERATURE"] = values.get("temperature") or "0.3"
    os.environ["LLM_KEEP_ALIVE"] = values.get("keep_alive") or "30m"
    os.environ["LLM_API_KEY"] = values.get("key") or ""
    os.environ["MODEL_ADMIN_KEY"] = values.get("admin") or "local-admin"
    return _port(values.get("port"))


def _port(value: str | None) -> int:
    try:
        port = int(value or "8181")
    except ValueError:
        return 8181
    if 1 <= port <= 65535:
        return port
    return 8181
