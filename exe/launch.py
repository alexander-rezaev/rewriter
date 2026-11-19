"""Windows program: start the site and read the Ollama address from ollama.txt."""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _home() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _say(text: str) -> None:
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("utf-8", errors="replace").decode("ascii", errors="replace"), flush=True)


def _open_when_ready(url: str) -> None:
    import urllib.request

    for _ in range(50):
        try:
            urllib.request.urlopen(url + "/health", timeout=1)
            webbrowser.open(url)
            return
        except Exception:
            time.sleep(0.2)


def main() -> None:
    from app.connection import apply_connection

    folder = _home()
    config = folder / "ollama.txt"
    port = apply_connection(config)
    url = f"http://127.0.0.1:{port}"
    _say(f"Сайт: {url}")
    _say(f"Ollama: {os.environ.get('LLM_BASE_URL', '')}")
    _say(f"Подключение: {config}")
    _say("Закройте это окно, чтобы остановить сайт.")

    import uvicorn
    from app.main import app

    if os.environ.get("REWRITER_NO_BROWSER") != "1":
        threading.Thread(target=_open_when_ready, args=(url,), daemon=True).start()
    try:
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
    except OSError as exc:
        busy = getattr(exc, "winerror", None) == 10048 or exc.errno in {98, 48, 10048}
        if busy:
            _say(f"Порт {port} занят. В ollama.txt поменяйте port и запустите снова.")
        raise


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    main()
