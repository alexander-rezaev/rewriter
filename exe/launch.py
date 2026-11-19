"""Windows program: start the site and read the Ollama address from ollama.txt."""

from __future__ import annotations

import os
import subprocess
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


def _browser_candidates() -> list[Path]:
    roots = [os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", "")]
    local = os.environ.get("LOCALAPPDATA", "")
    found: list[Path] = []
    for root in roots:
        if not root:
            continue
        found.append(Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
        found.append(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe")
    if local:
        found.append(Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe")
        found.append(Path(local) / "Yandex" / "YandexBrowser" / "Application" / "browser.exe")
    return [path for path in found if path.is_file()]


def _open_without_proxy(url: str) -> bool:
    """A workplace proxy intercepts 127.0.0.1 and the page then shows a generic failure."""
    browsers = _browser_candidates()
    if not browsers:
        return False
    profile = Path(os.environ.get("TEMP", ".")) / "RewriterBrowser"
    try:
        profile.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(
            [
                str(browsers[0]),
                f"--user-data-dir={profile}",
                "--no-proxy-server",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-sync",
                f"--app={url}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return True


def _open_when_ready(url: str) -> None:
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(50):
        try:
            with opener.open(url + "/health", timeout=1):
                pass
            if _open_without_proxy(url):
                _say("Браузер открыт без системного прокси.")
            else:
                webbrowser.open(url)
                _say("Если текст не обрабатывается, добавьте 127.0.0.1 в исключения прокси.")
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
