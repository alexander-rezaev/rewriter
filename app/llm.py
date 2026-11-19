from __future__ import annotations

import contextvars
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from difflib import SequenceMatcher

import httpx

from app.chunks import (
    REWRITE_CHUNK_LIMIT,
    context_tail,
    extract_facts,
    should_proofread_chunk,
    should_retry,
    split_chunks,
)
from app.proofread_guard import constrain_proofread, restore_guillemets
from app.prompts import (
    GRAMMAR_PROMPT,
    PROOFREAD_PROMPT,
    SYSTEM_PROMPT,
    build_proofread_prompt,
    build_user_prompt,
    format_terms_block,
)
from app.styles import Style
from app.tables import protect_tables, restore_tables
from app.terms import protect_terms, restore_terms

THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
FENCE_RE = re.compile(r"^```(?:\w+)?\s*|\s*```$", re.MULTILINE)
MARKUP_LINE_RE = re.compile(r"^[\s\-–—*_|`#>]+$")
COMMENTARY_RE = re.compile(
    r"(?is)\n+(?:here's why|let me know|explanation|here's a breakdown|"
    r"the sentence is already|пояснение|комментарий).*"
)
PREFIX_RE = re.compile(
    r"(?im)^(the corrected sentence is:\s*|corrected:\s*|исправленный текст:\s*)"
)
DICT_TAIL_RE = re.compile(
    r"(?is)\n+\s*(?:Словарь терминов|Словарь\s*:|Термины\s*:|Dictionary of terms)\b.*$"
)
DICT_LINE_RE = re.compile(r"(?im)^\s*Словарь терминов\b[^\n]*\n?")
UNCERTAIN_LINE_RE = re.compile(
    r"(?im)\n+\s*(?:НЕУВЕРЕННО|СОМНЕНИЯ)\s*:\s*(.+)\s*$"
)
BRACE_UNCERTAIN_RE = re.compile(r"\{\{(.+?)\}\}")
NONE_UNCERTAIN_RE = re.compile(r"^(нет|none|-|—)$", re.IGNORECASE)


class CancelToken:
    """Stops the Ollama request when the browser aborts."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._client: httpx.Client | None = None
        self._guard = threading.Lock()

    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()
        with self._guard:
            client = self._client
        if client is not None:
            client.close()

    def bind(self, client: httpx.Client) -> None:
        with self._guard:
            self._client = client
            already = self._event.is_set()
        if already:
            client.close()

    def unbind(self, client: httpx.Client) -> None:
        with self._guard:
            if self._client is client:
                self._client = None


_cancel_token: contextvars.ContextVar[CancelToken | None] = contextvars.ContextVar(
    "llm_cancel",
    default=None,
)


def current_cancel_token() -> CancelToken | None:
    return _cancel_token.get()


def bind_cancel_token(token: CancelToken) -> contextvars.Token[CancelToken | None]:
    return _cancel_token.set(token)


def reset_cancel_token(reset: contextvars.Token[CancelToken | None]) -> None:
    _cancel_token.reset(reset)


@dataclass
class CorrectionResult:
    text: str
    uncertain: list[str]
    model_changed: bool = False


class LLMError(Exception):
    def __init__(self, message: str, status_code: int = 502, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


_LLAMA_BACKENDS = {
    "llama",
    "llama-cpp",
    "llama.cpp",
    "llamacpp",
    "kepler",
    "sm35",
    "llama-cpp-kepler",
    "llama-cpp-kepler:sm35",
}


def _backend_from_env() -> str:
    raw = os.getenv("LLM_BACKEND", "ollama").strip().lower().replace("_", "-")
    if raw in _LLAMA_BACKENDS:
        return "llama"
    if raw in {"", "ollama"}:
        return "ollama"
    raise LLMError(
        "Неизвестный LLM_BACKEND. Допустимо ollama или llama.",
        status_code=500,
    )


def _service_name(backend: str) -> str:
    return "llama.cpp" if backend == "llama" else "Ollama"


@dataclass(frozen=True)
class LLMSettings:
    base_url: str
    api_key: str
    model: str
    rewrite_model: str
    proofread_model: str
    timeout: float
    temperature: float
    backend: str

    @classmethod
    def from_env(cls) -> LLMSettings:
        fallback = os.getenv("LLM_MODEL", "qwen3.5:9b")
        return cls(
            base_url=os.getenv("LLM_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
            api_key=os.getenv("LLM_API_KEY", ""),
            model=fallback,
            rewrite_model=os.getenv("LLM_REWRITE_MODEL") or fallback,
            proofread_model=os.getenv("LLM_PROOFREAD_MODEL") or fallback,
            timeout=float(os.getenv("LLM_TIMEOUT", "120")),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
            backend=_backend_from_env(),
        )


def _api_root(base_url: str) -> str:
    root = base_url.rstrip("/")
    for suffix in ("/v1", "/api"):
        if root.endswith(suffix):
            root = root[: -len(suffix)]
            break
    return root


def _chat_url(base_url: str) -> str:
    return f"{_api_root(base_url)}/api/chat"


def _generate_url(base_url: str) -> str:
    return f"{_api_root(base_url)}/api/generate"


def _llama_chat_url(base_url: str) -> str:
    return f"{_api_root(base_url)}/v1/chat/completions"


def _llama_models_url(base_url: str) -> str:
    return f"{_api_root(base_url)}/v1/models"


def _alnum(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def _clean_output(text: str) -> str:
    text = THINK_BLOCK_RE.sub("", text)
    if "Corrected:" in text:
        text = text.split("Corrected:")[-1]
    text = FENCE_RE.sub("", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    lines = [line for line in text.splitlines() if not MARKUP_LINE_RE.fullmatch(line)]
    return "\n".join(lines).strip()


def _extract_proofread_output(source: str, raw: str) -> str:
    text = PREFIX_RE.sub("", _clean_output(raw)).strip()
    text = COMMENTARY_RE.sub("", text).strip()
    if not text:
        return text
    src_letters = _alnum(source)
    if not src_letters:
        return text
    best = text
    best_score = SequenceMatcher(None, src_letters, _alnum(text)).ratio()
    if best_score >= 0.55:
        return text
    for chunk in (part.strip() for part in re.split(r"\n+", text) if part.strip()):
        score = SequenceMatcher(None, src_letters, _alnum(chunk)).ratio()
        if score > best_score:
            best, best_score = chunk, score
    return best


def strip_prompt_leak(text: str, terms: list[str] | None = None) -> str:
    cleaned = DICT_TAIL_RE.sub("", text or "").strip()
    cleaned = DICT_LINE_RE.sub("", cleaned).strip()
    if terms:
        listed = {item.lower() for item in terms}
        lines = cleaned.splitlines()
        while lines:
            last = lines[-1].strip().strip(".;")
            parts = [part.strip() for part in re.split(r"[;,]", last) if part.strip()]
            if parts and all(part.lower() in listed for part in parts):
                lines.pop()
                continue
            break
        cleaned = "\n".join(lines).strip()
    return cleaned


def split_uncertain(raw: str) -> tuple[str, list[str]]:
    text = raw or ""
    found: list[str] = []
    match = UNCERTAIN_LINE_RE.search(text)
    if match:
        text = text[: match.start()]
        payload = match.group(1).strip()
        if not NONE_UNCERTAIN_RE.fullmatch(payload):
            for part in re.split(r"[;,]", payload):
                word = part.strip().strip(".")
                if word:
                    found.append(word)
    for brace in BRACE_UNCERTAIN_RE.finditer(text):
        word = brace.group(1).strip()
        if word:
            found.append(word)
    text = BRACE_UNCERTAIN_RE.sub(r"\1", text)
    unique: list[str] = []
    seen: set[str] = set()
    for word in found:
        key = word.lower()
        if key not in seen:
            seen.add(key)
            unique.append(word)
    return text.strip(), unique


def context_limit() -> int:
    """Maximum context in tokens. Set LLM_NUM_CTX in docker-compose.yml."""
    raw = os.getenv("LLM_NUM_CTX", "4096").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 4096
    return max(512, value)


def fit_num_ctx(*parts: str, cap: int | None = None, floor: int = 512) -> int:
    """Context window that fits this prompt, never above LLM_NUM_CTX."""
    if cap is None:
        cap = context_limit()
    chars = sum(len(part) for part in parts)
    estimate = chars + max(512, chars // 2)
    rounded = ((max(estimate, 1) + 511) // 512) * 512
    return max(floor, min(cap, rounded))


_http_guard = threading.Lock()
_http_client: httpx.Client | None = None
_http_read_timeout: float | None = None
_models_cache: tuple[float, str, list[dict[str, str | int]]] | None = None
_MODELS_TTL = 20.0


def _borrow_client(settings: LLMSettings) -> httpx.Client:
    global _http_client, _http_read_timeout
    timeout = httpx.Timeout(connect=10.0, read=settings.timeout, write=60.0, pool=10.0)
    with _http_guard:
        if (
            _http_client is None
            or _http_client.is_closed
            or _http_read_timeout != settings.timeout
            or _http_client.trust_env
        ):
            if _http_client is not None and not _http_client.is_closed:
                _http_client.close()
            # The Windows proxy would intercept 127.0.0.1 and answer with an empty 503.
            _http_client = httpx.Client(timeout=timeout, trust_env=False)
            _http_read_timeout = settings.timeout
        return _http_client


def _raise_if_cancelled() -> None:
    token = _cancel_token.get()
    if token is not None and token.cancelled():
        raise LLMError("Запрос остановлен.", status_code=499)


def _status_failure(response: httpx.Response, service: str) -> LLMError:
    try:
        raw = response.read().decode("utf-8", errors="replace")
    except Exception:
        raw = ""
    return _http_failure(service, response.status_code, raw)


def _connect_message(service: str, address: str) -> str:
    where = f" по адресу {address}" if address else ""
    return (
        f"Не удалось подключиться к {service}{where}. "
        "Проверьте, что служба запущена. В программе адрес записан в файле ollama.txt."
    )


def _is_connect_failure(exc: Exception) -> bool:
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.UnsupportedProtocol, ConnectionError)):
        return True
    return type(exc).__name__ in {"ConnectError", "ConnectTimeout", "PoolTimeout", "UnsupportedProtocol", "InvalidURL"}


def _transport_failure(exc: Exception, service: str, address: str = "") -> LLMError | None:
    """Turn a dropped Ollama connection into the same advice as an empty 503."""
    if _is_connect_failure(exc):
        return LLMError(_connect_message(service, address), status_code=503)
    if isinstance(exc, httpx.TimeoutException) or type(exc).__name__ in {"ReadTimeout", "WriteTimeout"}:
        return LLMError(
            "Модель не ответила вовремя. Попробуйте более короткий текст или увеличьте LLM_TIMEOUT.",
            status_code=504,
        )
    if isinstance(exc, httpx.TransportError) or type(exc).__module__.startswith(("httpx", "httpcore")):
        return LLMError(
            f"{service} не ответила. Подождите загрузку модели или перезапустите {service}.",
            status_code=503,
            retryable=True,
        )
    return None


def _http_failure(service: str, status: int, raw: str) -> LLMError:
    if status == 503 and not raw.strip():
        return LLMError(
            f"{service} не ответила, код 503. "
            f"Подождите загрузку модели или перезапустите {service}.",
            status_code=503,
            retryable=True,
        )
    detail = _decode_error_body(raw, service)
    if status == 503:
        return LLMError(
            f"{service} не ответила, код 503. {detail}",
            status_code=503,
            retryable=True,
        )
    return LLMError(f"{service} отклонила запрос: {detail}", status_code=502)


def _decode_error_body(raw: str, service: str) -> str:
    text = raw.strip() or f"{service} вернула ошибку"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    error = payload.get("error", text)
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error)


def _event_from_line(line: str) -> dict | None:
    text = line.strip()
    if not text or text.startswith(":"):
        return None
    if text.startswith("data:"):
        text = text[5:].strip()
    if not text:
        return None
    if text == "[DONE]":
        return {"_done": True}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _event_piece(data: dict, service: str, backend: str) -> tuple[str, bool]:
    if data.get("_done"):
        return "", True
    error = data.get("error")
    if error:
        message = error.get("message") if isinstance(error, dict) else error
        raise LLMError(f"{service} отклонила запрос: {message}", status_code=502)
    if backend == "llama":
        choices = data.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            return "", False
        choice = choices[0]
        delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        text = delta.get("content") if delta.get("content") is not None else message.get("content")
        return (text if isinstance(text, str) else ""), bool(choice.get("finish_reason"))
    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    text = message.get("content") or data.get("response") or ""
    return (text if isinstance(text, str) else ""), bool(data.get("done"))


def _post_stream(url: str, payload: dict, settings: LLMSettings) -> dict:
    service = _service_name(settings.backend)
    headers = {"Content-Type": "application/json"}
    if settings.api_key:
        headers["Authorization"] = f"Bearer {settings.api_key}"
    token = _cancel_token.get()
    client = _borrow_client(settings)
    if token is not None:
        token.bind(client)
    timed_out = threading.Event()
    finished = threading.Event()

    def _expire() -> None:
        if not finished.wait(settings.timeout):
            timed_out.set()
            client.close()

    threading.Thread(target=_expire, daemon=True).start()
    parts: list[str] = []
    reuse = True
    try:
        _raise_if_cancelled()
        with client.stream("POST", url, json=payload, headers=headers) as response:
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise _status_failure(exc.response, service) from exc
            lines = response.iter_lines()
            while True:
                _raise_if_cancelled()
                if timed_out.is_set():
                    raise LLMError(
                        "Модель не ответила вовремя. Попробуйте более короткий текст или увеличьте LLM_TIMEOUT.",
                        status_code=504,
                    )
                try:
                    line = next(lines)
                except StopIteration:
                    break
                if not line:
                    continue
                data = _event_from_line(line)
                if data is None:
                    continue
                piece, done = _event_piece(data, service, settings.backend)
                if piece:
                    parts.append(piece)
                if done:
                    break
    except LLMError:
        reuse = False
        raise
    except Exception as exc:
        reuse = False
        _raise_if_cancelled()
        if timed_out.is_set():
            raise LLMError(
                "Модель не ответила вовремя. Попробуйте более короткий текст или увеличьте LLM_TIMEOUT.",
                status_code=504,
            ) from exc
        mapped = _transport_failure(exc, service, settings.base_url)
        if mapped is not None:
            raise mapped from exc
        raise
    finally:
        finished.set()
        if token is not None:
            token.unbind(client)
        if not reuse or timed_out.is_set() or (token is not None and token.cancelled()):
            client.close()
    content = "".join(parts)
    if payload.get("messages") is not None or "messages" in payload:
        return {"message": {"content": content}}
    return {"response": content}


_LOAD_TRIES = 16
_LOAD_PAUSE = 3.0


def _post_ollama(url: str, payload: dict, settings: LLMSettings) -> dict:
    body = dict(payload)
    body["stream"] = True
    keep_alive = os.getenv("LLM_KEEP_ALIVE", "30m").strip()
    if keep_alive:
        body["keep_alive"] = keep_alive
    last: LLMError | None = None
    for attempt in range(_LOAD_TRIES):
        try:
            return _post_stream(url, body, settings)
        except LLMError as exc:
            last = exc
            if exc.status_code != 503 or not exc.retryable or attempt == _LOAD_TRIES - 1:
                raise
            _raise_if_cancelled()
            time.sleep(_LOAD_PAUSE)
            _raise_if_cancelled()
    if last is not None:
        raise last
    raise LLMError("Ollama не ответила.", status_code=503)


def _post_llama(url: str, payload: dict, settings: LLMSettings) -> dict:
    body = dict(payload)
    body["stream"] = True
    body.pop("keep_alive", None)
    body.pop("think", None)
    body.pop("options", None)
    return _post_stream(url, body, settings)


def _models_from_payload(payload: dict, backend: str) -> list[dict[str, str | int]]:
    found: dict[str, int] = {}
    items = payload.get("data") if backend == "llama" else payload.get("models")
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = item.get("id") if backend == "llama" else (item.get("name") or item.get("model"))
        if not isinstance(name, str) or not name.strip():
            continue
        size = item.get("size") or 0
        if backend == "llama":
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            size = meta.get("size") or size
        found[name.strip()] = int(size) if isinstance(size, int) else 0
    return [{"name": name, "size": found[name]} for name in sorted(found)]


def list_installed_models() -> list[dict[str, str | int]]:
    global _models_cache
    now = time.monotonic()
    settings = LLMSettings.from_env()
    cache_key = f"{settings.backend}|{settings.base_url}"
    if (
        _models_cache is not None
        and now - _models_cache[0] < _MODELS_TTL
        and _models_cache[1] == cache_key
    ):
        return _models_cache[2]
    service = _service_name(settings.backend)
    url = (
        _llama_models_url(settings.base_url)
        if settings.backend == "llama"
        else f"{_api_root(settings.base_url)}/api/tags"
    )
    headers = {}
    if settings.api_key:
        headers["Authorization"] = f"Bearer {settings.api_key}"
    try:
        response = httpx.get(url, headers=headers, timeout=10, trust_env=False)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise LLMError(
            f"Не удалось получить список моделей {service}.",
            status_code=503,
        ) from exc
    if not isinstance(payload, dict):
        payload = {}
    models = _models_from_payload(payload, settings.backend)
    if settings.backend == "llama" and not models:
        models = [{"name": settings.model, "size": 0}]
    _models_cache = (now, cache_key, models)
    return models


def _complete(
    system_prompt: str,
    user_prompt: str,
    temperature: float | None = None,
    *,
    model: str | None = None,
    strict: bool = False,
    use_generate: bool = False,
    num_ctx: int | None = None,
    seed: int | None = None,
    clean: bool = True,
) -> str:
    _raise_if_cancelled()
    settings = LLMSettings.from_env()
    model_name = model or settings.rewrite_model
    options: dict[str, float | int] = {
        "temperature": settings.temperature if temperature is None else temperature,
        "repeat_penalty": 1.0,
    }
    if strict:
        options.update({"top_p": 0.3, "top_k": 20, "seed": 0})
    options["num_ctx"] = num_ctx if num_ctx else fit_num_ctx(system_prompt, user_prompt)
    if seed is not None:
        options["seed"] = seed
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    if use_generate:
        prompt = user_prompt if not system_prompt.strip() else f"{system_prompt}\n\n{user_prompt}"
        messages = [{"role": "user", "content": prompt}]

    if settings.backend == "llama":
        llama_body: dict = {
            "model": model_name,
            "messages": messages,
            "temperature": options["temperature"],
            "repeat_penalty": options["repeat_penalty"],
            "stream": False,
        }
        if "top_p" in options:
            llama_body["top_p"] = options["top_p"]
        if "top_k" in options:
            llama_body["top_k"] = options["top_k"]
        if "seed" in options:
            llama_body["seed"] = options["seed"]
        data = _post_llama(_llama_chat_url(settings.base_url), llama_body, settings)
        raw = (data.get("message") or {}).get("content") or ""
    elif use_generate:
        prompt = messages[0]["content"]
        data = _post_ollama(
            _generate_url(settings.base_url),
            {
                "model": model_name,
                "prompt": prompt,
                "stream": False,
                "think": False,
                "options": options,
            },
            settings,
        )
        raw = data.get("response") or ""
    else:
        data = _post_ollama(
            _chat_url(settings.base_url),
            {
                "model": model_name,
                "stream": False,
                "think": False,
                "messages": messages,
                "options": options,
            },
            settings,
        )
        raw = (data.get("message") or {}).get("content") or ""

    result = _clean_output(raw) if clean else (raw or "").strip()
    if not result:
        where = "загружена в llama.cpp" if settings.backend == "llama" else "установлена в Ollama"
        raise LLMError(f"Модель вернула пустой ответ. Проверьте, что нужная модель {where}.")
    return result


def _with_terms(system: str, terms: list[str]) -> str:
    block = format_terms_block(terms).strip()
    if not block:
        return system
    return f"{system}\n{block}"


_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "‑": "-"})
_LOOKALIKES = str.maketrans(
    {
        "a": "а",
        "e": "е",
        "o": "о",
        "p": "р",
        "c": "с",
        "x": "х",
        "y": "у",
        "k": "к",
        "h": "н",
        "m": "м",
        "t": "т",
        "b": "в",
    }
)


def _fold_text(text: str) -> str:
    folded = (text or "").casefold().replace("ё", "е")
    folded = folded.translate(_DASHES).translate(_LOOKALIKES)
    for mark in "«»\"“”„":
        folded = folded.replace(mark, "")
    folded = re.sub(r"(?<=\d),(?=\d)", ".", folded)
    return "".join(folded.split())


def _missing_facts(source: str, result: str) -> list[str]:
    """Facts from the source chunk that the answer no longer contains."""
    folded = _fold_text(result)
    missing: list[str] = []
    for fact in extract_facts(source):
        if _fold_text(fact) not in folded:
            missing.append(fact)
    return missing


def _drop_echoed_context(text: str, context: str) -> str:
    """Drop a previous fragment if the model copied it into the new answer."""
    body = text or ""
    tail = context_tail(context)
    if not tail:
        return body
    stripped = body.lstrip()
    if stripped.startswith(tail):
        return stripped[len(tail) :].lstrip()
    return body


def rewrite_text(
    text: str,
    style: Style,
    terms: list[str] | None = None,
    model: str | None = None,
    on_progress=None,
) -> str:
    shielded, tables = protect_tables(text)
    protected, relevant = protect_terms(shielded, terms or [])
    settings = LLMSettings.from_env()
    system = _with_terms(SYSTEM_PROMPT, relevant)
    chosen = model or settings.rewrite_model
    chunks = split_chunks(protected, limit=REWRITE_CHUNK_LIMIT)
    total = len(chunks)
    if on_progress:
        on_progress(0, total)
    pieces: list[str] = []
    previous = ""
    for index, chunk in enumerate(chunks, start=1):
        _raise_if_cancelled()
        core = chunk.strip()
        if not core:
            pieces.append(chunk)
            if on_progress:
                on_progress(index, total, restore_tables("".join(pieces), tables))
            continue
        leading = chunk[: len(chunk) - len(chunk.lstrip())]
        trailing = chunk[len(chunk.rstrip()) :]
        context = context_tail(previous)
        facts = extract_facts(core)
        raw = _complete(
            system,
            build_user_prompt(core, style, context=context, facts=facts),
            model=chosen,
        )
        piece = _drop_echoed_context(strip_prompt_leak(restore_terms(raw, relevant), relevant), context)
        missing = _missing_facts(core, piece)
        if missing:
            _raise_if_cancelled()
            retried = _complete(
                system,
                build_user_prompt(core, style, context=context, facts=facts, dropped=missing),
                model=chosen,
            )
            second = _drop_echoed_context(
                strip_prompt_leak(restore_terms(retried, relevant), relevant),
                context,
            )
            if len(_missing_facts(core, second)) < len(missing):
                piece = second
        pieces.append(leading + piece + trailing)
        previous += piece
        if on_progress:
            on_progress(index, total, restore_tables("".join(pieces), tables))
    restored = restore_guillemets(shielded, "".join(pieces))
    return strip_prompt_leak(restore_tables(restored, tables), relevant)


def _same_text(left: str, right: str) -> bool:
    return " ".join((left or "").split()) == " ".join((right or "").split())


def _finalize_correction(
    source: str,
    raw: str,
    terms: list[str],
    *,
    grammar: bool,
) -> CorrectionResult:
    body, parsed = split_uncertain(raw)
    uncertain = [] if grammar else parsed
    result = _extract_proofread_output(source, body)
    result = strip_prompt_leak(result, terms)
    result = UNCERTAIN_LINE_RE.sub("", result).strip()
    result = BRACE_UNCERTAIN_RE.sub(r"\1", result)
    if not result:
        raise LLMError("Модель вернула пустой ответ. Проверьте, что нужная модель установлена в Ollama.")
    guarded = constrain_proofread(source, result, allow_inflection=grammar)
    kept: list[str] = []
    if not grammar:
        seen: set[str] = set()
        for word in uncertain:
            token = word.strip().strip(".,;:!?")
            if len(token) < 2:
                continue
            key = token.lower()
            if key in seen:
                continue
            if re.search(rf"(?<!\w){re.escape(token)}(?!\w)", guarded, re.IGNORECASE | re.UNICODE):
                seen.add(key)
                kept.append(token)
    return CorrectionResult(
        text=guarded,
        uncertain=kept,
        model_changed=not _same_text(result, source),
    )


def _correct_chunk(
    chunk: str,
    system: str,
    *,
    grammar: bool,
    model: str,
    context: str = "",
) -> CorrectionResult:
    _raise_if_cancelled()
    if not chunk.strip():
        return CorrectionResult(text=chunk, uncertain=[])
    core = chunk.strip()
    leading = chunk[: len(chunk) - len(chunk.lstrip())]
    trailing = chunk[len(chunk.rstrip()) :]
    user = build_proofread_prompt(core, context=context)
    raw = _complete(
        system,
        user,
        temperature=0.0,
        model=model,
        strict=True,
        seed=0,
        clean=False,
    )
    result = _finalize_correction(core, raw, [], grammar=grammar)
    if not should_retry(core, result.text, result.model_changed):
        return CorrectionResult(
            text=leading + result.text + trailing,
            uncertain=result.uncertain,
            model_changed=result.model_changed,
        )
    nudge = (
        "В исходном тексте есть ошибки. Не копируй его без правок. "
        "Исправь орфографию и пунктуацию и верни только исправленный текст."
        if not grammar
        else "В исходном тексте есть ошибки падежа или согласования. Не копируй его без правок."
    )
    raw_retry = _complete(
        system,
        f"{user}\n\n{nudge}",
        temperature=0.2,
        model=model,
        strict=False,
        seed=1,
        clean=False,
    )
    retry = _finalize_correction(core, raw_retry, [], grammar=grammar)
    chosen = result if _same_text(retry.text, core) else retry
    return CorrectionResult(
        text=leading + chosen.text + trailing,
        uncertain=chosen.uncertain,
        model_changed=chosen.model_changed,
    )


def proofread_text(
    text: str,
    terms: list[str] | None = None,
    *,
    grammar: bool = False,
    model: str | None = None,
    on_progress=None,
) -> CorrectionResult:
    shielded, tables = protect_tables(text)
    protected, relevant = protect_terms(shielded, terms or [])
    settings = LLMSettings.from_env()
    chosen = model or settings.proofread_model
    system = _with_terms(GRAMMAR_PROMPT if grammar else PROOFREAD_PROMPT, relevant)
    pieces: list[str] = []
    uncertain: list[str] = []
    seen: set[str] = set()
    chunks = split_chunks(protected)
    total = len(chunks)
    if on_progress:
        on_progress(0, total)
    previous = ""
    for index, chunk in enumerate(chunks, start=1):
        core = chunk.strip()
        if not grammar and core and not should_proofread_chunk(core):
            pieces.append(chunk)
            previous += core
            if on_progress:
                on_progress(index, total, restore_tables("".join(pieces), tables))
            continue
        corrected = _correct_chunk(
            chunk,
            system,
            grammar=grammar,
            model=chosen,
            context=context_tail(previous),
        )
        pieces.append(corrected.text)
        previous += corrected.text
        for word in corrected.uncertain:
            key = word.lower()
            if key not in seen:
                seen.add(key)
                uncertain.append(word)
        if on_progress:
            on_progress(index, total, restore_tables(restore_terms("".join(pieces), relevant), tables))
    joined = restore_tables(
        restore_guillemets(shielded, restore_terms("".join(pieces), relevant)),
        tables,
    )
    protected_words = {term.lower() for term in relevant}
    visible = [
        restore_terms(word, relevant)
        for word in uncertain
        if restore_terms(word, relevant).lower() not in protected_words
    ]
    return CorrectionResult(text=joined, uncertain=visible)
