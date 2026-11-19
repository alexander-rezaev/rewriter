import asyncio
import contextvars
import json
import os
import secrets
import threading
import time
import traceback
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.gzip import GZipMiddleware

from app.docx_text import docx_to_text
from app.feedback import add_idea, delete_idea, load_ideas, set_like
from app.highlight import highlight_proofread, highlight_rewrite
from app.llm import (
    CancelToken,
    LLMError,
    LLMSettings,
    bind_cancel_token,
    list_installed_models,
    proofread_text,
    reset_cancel_token,
    rewrite_text,
)
from app.stats import add_rewrite, load_stats, set_app_like
from app.store import StoreError
from app.styles import get_style, list_styles
from app.paths import bundle_root
from app.terms import add_term, load_terms, remove_term, update_term

BASE_DIR = bundle_root()
app = FastAPI(title="Рерайтер")
_STREAM_API = {"/api/rewrite", "/api/proofread"}


class _PlainStream:
    """NDJSON progress must not sit in a gzip buffer."""

    def __init__(self, asgi):
        self.asgi = asgi

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") in _STREAM_API:
            headers = [
                (key, value)
                for key, value in scope.get("headers", [])
                if key.lower() != b"accept-encoding"
            ]
            scope = {**scope, "headers": headers}
        await self.asgi(scope, receive, send)


app.add_middleware(GZipMiddleware, minimum_size=512)
app.add_middleware(_PlainStream)
_llm_lock = asyncio.Lock()
_QUEUE_LIMIT = 8
_QUEUE_FULL = "Очередь заполнена. Попробуйте через несколько минут."
_seconds_per_1k = 45.0
_waiting: list["_Ticket"] = []
_running: "_Ticket | None" = None
_jobs: dict[str, CancelToken] = {}
_jobs_guard = threading.Lock()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _clean_input(value: str, empty: str) -> str:
    cleaned = value.encode("utf-8", "replace").decode("utf-8").strip()
    if not cleaned:
        raise ValueError(empty)
    return cleaned


def _unexpected_failure(exc: Exception) -> str:
    detail = " ".join(str(exc).split()) or exc.__class__.__name__
    if len(detail) > 180:
        detail = detail[:180] + "…"
    return f"Не удалось обработать текст. {detail}"


class Segment(BaseModel):
    text: str
    kind: str | None = None


class RewriteRequest(BaseModel):
    text: str = Field(..., min_length=1)
    style: str
    model: str | None = None
    request_id: str | None = None

    @field_validator("text", mode="before")
    @classmethod
    def text_not_blank(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("Введите текст для переписывания.")
        return _clean_input(value, "Введите текст для переписывания.")


class RewriteResponse(BaseModel):
    result: str
    segments: list[Segment]
    rewrites: int = 0


class ProofreadRequest(BaseModel):
    text: str = Field(..., min_length=1)
    grammar: bool = False
    model: str | None = None
    request_id: str | None = None

    @field_validator("text", mode="before")
    @classmethod
    def text_not_blank(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("Введите текст для проверки.")
        return _clean_input(value, "Введите текст для проверки.")


class StopRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)


class ProofreadResponse(BaseModel):
    result: str
    segments: list[Segment]


class ModelOption(BaseModel):
    name: str
    size: int = 0


class ModelsResponse(BaseModel):
    models: list[ModelOption]
    default: str
    warning: str | None = None


class TermsResponse(BaseModel):
    terms: list[str]


class TermRequest(BaseModel):
    term: str = Field(..., min_length=1)

    @field_validator("term")
    @classmethod
    def term_not_blank(cls, value: str) -> str:
        cleaned = " ".join(value.split()).strip()
        if not cleaned:
            raise ValueError("Введите термин.")
        return cleaned


class IdeaRequest(BaseModel):
    name: str = ""
    text: str = ""

    @field_validator("name", "text")
    @classmethod
    def idea_not_blank(cls, value: str) -> str:
        return " ".join(value.split()).strip()

    @field_validator("text")
    @classmethod
    def idea_has_text(cls, value: str) -> str:
        if not value:
            raise ValueError("Напишите идею.")
        return value


class LikeRequest(BaseModel):
    liked: bool


class TermUpdateRequest(BaseModel):
    old: str = Field(..., min_length=1)
    term: str = Field(..., min_length=1)

    @field_validator("old", "term")
    @classmethod
    def fields_not_blank(cls, value: str) -> str:
        cleaned = " ".join(value.split()).strip()
        if not cleaned:
            raise ValueError("Введите термин.")
        return cleaned


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _admin_key() -> str:
    return os.getenv("MODEL_ADMIN_KEY", "").strip()


def _model_key_ok(request: Request) -> bool:
    expected = _admin_key()
    provided = (request.headers.get("x-model-key") or "").strip()
    if not expected or not provided or len(provided) != len(expected):
        return False
    return secrets.compare_digest(provided, expected)


def _configured_models() -> set[str]:
    settings = LLMSettings.from_env()
    return {settings.model, settings.rewrite_model, settings.proofread_model}


def _clean_model(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


async def _resolve_model(value: str | None) -> str | None:
    chosen = _clean_model(value)
    if chosen is None:
        return None
    try:
        installed = {item["name"] for item in await asyncio.to_thread(list_installed_models)}
    except LLMError:
        if chosen not in _configured_models():
            raise HTTPException(status_code=422, detail="Этой модели нет в списке.") from None
        return chosen
    if chosen not in installed:
        where = "llama.cpp" if LLMSettings.from_env().backend == "llama" else "Ollama"
        raise HTTPException(status_code=422, detail=f"Этой модели нет в {where}.")
    return chosen


def _job_id(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 80 or any(char.isspace() for char in cleaned):
        raise HTTPException(status_code=422, detail="Некорректный идентификатор запроса.")
    return cleaned


def _remember_job(job_id: str | None, token: CancelToken) -> None:
    if not job_id:
        return
    with _jobs_guard:
        _jobs[job_id] = token


def _forget_job(job_id: str | None, token: CancelToken) -> None:
    if not job_id:
        return
    with _jobs_guard:
        if _jobs.get(job_id) is token:
            _jobs.pop(job_id, None)


class _Ticket:
    def __init__(self, chars: int, token: CancelToken) -> None:
        self.chars = max(1, chars)
        self.token = token
        self.turn = asyncio.Event()
        self.started_at = 0.0
        self.acquired = False


def _reset_model_queue() -> None:
    global _running, _seconds_per_1k
    _waiting.clear()
    _running = None
    _seconds_per_1k = 45.0


def _queue_full() -> bool:
    return _running is not None and len(_waiting) >= _QUEUE_LIMIT


def _job_seconds(chars: int) -> float:
    return min(20 * 60, max(12.0, _seconds_per_1k * max(chars, 200) / 1000))


def _remaining(ticket: _Ticket) -> float:
    total = _job_seconds(ticket.chars)
    if not ticket.started_at:
        return total
    left = total - (time.monotonic() - ticket.started_at)
    if left >= 10:
        return left
    return max(20.0, total * 0.35)


def _remember_rate(ticket: _Ticket) -> None:
    global _seconds_per_1k
    if not ticket.acquired or ticket.token.cancelled() or not ticket.started_at:
        return
    elapsed = time.monotonic() - ticket.started_at
    if elapsed < 3:
        return
    sample = min(180.0, max(8.0, elapsed / max(ticket.chars, 200) * 1000))
    _seconds_per_1k = _seconds_per_1k * 0.65 + sample * 0.35


def _enqueue(ticket: _Ticket) -> bool:
    global _running
    if _running is None and not _waiting:
        _running = ticket
        ticket.started_at = time.monotonic()
        ticket.turn.set()
        return True
    if len(_waiting) >= _QUEUE_LIMIT:
        return False
    _waiting.append(ticket)
    return True


def _handoff(ticket: _Ticket) -> None:
    global _running
    if _running is ticket:
        _remember_rate(ticket)
        _running = _waiting.pop(0) if _waiting else None
        if _running is not None:
            _running.started_at = time.monotonic()
            _running.turn.set()
        return
    try:
        _waiting.remove(ticket)
    except ValueError:
        return


def _queue_snapshot(ticket: _Ticket) -> dict[str, int]:
    if ticket.turn.is_set():
        return {"ahead": 0, "wait": 0}
    try:
        index = _waiting.index(ticket)
    except ValueError:
        return {"ahead": 0, "wait": 0}
    ahead: list[_Ticket] = []
    if _running is not None:
        ahead.append(_running)
    ahead.extend(_waiting[:index])
    return {"ahead": len(ahead), "wait": max(0, int(round(sum(_remaining(item) for item in ahead))))}


def _release_model() -> None:
    if _llm_lock.locked():
        _llm_lock.release()


def _stream_job(
    request: Request,
    produce,
    request_id: str | None = None,
    chars: int = 0,
) -> StreamingResponse:
    token = CancelToken()
    _remember_job(request_id, token)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def on_progress(done: int, total: int, text: str | None = None) -> None:
        event: dict[str, int | str] = {"type": "progress", "done": done, "total": total}
        if text:
            event["text"] = text
        loop.call_soon_threadsafe(queue.put_nowait, event)

    async def watch() -> None:
        try:
            while not token.cancelled():
                if await request.is_disconnected():
                    token.cancel()
                    return
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            return

    watcher = asyncio.create_task(watch())

    async def worker() -> None:
        reset = bind_cancel_token(token)
        context = contextvars.copy_context()
        ticket = _Ticket(chars, token)
        acquired = False
        try:
            if token.cancelled():
                raise LLMError("Запрос остановлен.", status_code=499)
            if not _enqueue(ticket):
                await queue.put({"type": "error", "detail": _QUEUE_FULL})
                return
            while not ticket.turn.is_set():
                if token.cancelled():
                    raise LLMError("Запрос остановлен.", status_code=499)
                await queue.put({"type": "queue", **_queue_snapshot(ticket)})
                try:
                    await asyncio.wait_for(ticket.turn.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
            if token.cancelled():
                raise LLMError("Запрос остановлен.", status_code=499)
            await queue.put({"type": "queue", "ahead": 0, "wait": 0})
            await _llm_lock.acquire()
            acquired = True
            ticket.acquired = True
            if token.cancelled():
                raise LLMError("Запрос остановлен.", status_code=499)
            value = await asyncio.to_thread(context.run, produce, on_progress)
            await queue.put({"type": "result", **value})
        except LLMError as exc:
            await queue.put({"type": "error", "detail": exc.message})
        except Exception as exc:
            traceback.print_exc()
            await queue.put({"type": "error", "detail": _unexpected_failure(exc)})
        finally:
            if acquired:
                _release_model()
            _handoff(ticket)
            token.cancel()
            _forget_job(request_id, token)
            watcher.cancel()
            try:
                reset_cancel_token(reset)
            finally:
                await queue.put(None)

    asyncio.create_task(worker())

    async def generate():
        while True:
            item = await queue.get()
            if item is None:
                break
            yield json.dumps(item, ensure_ascii=False).encode() + b"\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.post("/api/stop")
async def stop_request(payload: StopRequest) -> dict[str, bool]:
    with _jobs_guard:
        token = _jobs.get(payload.id.strip())
    if token is not None:
        token.cancel()
    return {"stopped": True}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"styles": list_styles(), "model_choice": bool(_admin_key())},
    )


@app.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "terms.html", {})


@app.get("/api/terms", response_model=TermsResponse)
async def get_terms() -> TermsResponse:
    return TermsResponse(terms=load_terms())


@app.post("/api/terms", response_model=TermsResponse)
async def create_term(payload: TermRequest) -> TermsResponse:
    try:
        terms = add_term(payload.term)
    except StoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return TermsResponse(terms=terms)


@app.patch("/api/terms", response_model=TermsResponse)
async def patch_term(payload: TermUpdateRequest) -> TermsResponse:
    try:
        terms = update_term(payload.old, payload.term)
    except StoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return TermsResponse(terms=terms)


@app.delete("/api/terms", response_model=TermsResponse)
async def delete_term(term: str) -> TermsResponse:
    try:
        terms = remove_term(term)
    except StoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return TermsResponse(terms=terms)


@app.get("/api/models", response_model=ModelsResponse)
async def models(request: Request) -> ModelsResponse:
    if not _model_key_ok(request):
        raise HTTPException(status_code=403, detail="Выбор модели недоступен.")
    settings = LLMSettings.from_env()
    default = settings.rewrite_model
    try:
        installed = await asyncio.to_thread(list_installed_models)
    except LLMError as exc:
        fallback = [name for name in (settings.rewrite_model, settings.proofread_model, settings.model) if name]
        unique: list[ModelOption] = []
        seen: set[str] = set()
        for name in fallback:
            if name not in seen:
                seen.add(name)
                unique.append(ModelOption(name=name))
        return ModelsResponse(models=unique, default=default, warning=exc.message)
    names = [item["name"] for item in installed]
    if default not in names and names:
        default = names[0]
    return ModelsResponse(
        models=[ModelOption(name=item["name"], size=item["size"]) for item in installed],
        default=default,
    )


@app.post("/api/docx")
async def upload_docx(request: Request) -> dict[str, str]:
    if not _model_key_ok(request):
        raise HTTPException(status_code=403, detail="Загрузка Word доступна только администратору.")
    # The browser rejects a raw Cyrillic name in a header, so the client sends it encoded.
    name = unquote(request.headers.get("x-filename") or "").strip().lower()
    if not name.endswith(".docx"):
        raise HTTPException(status_code=422, detail="Нужен файл Word в формате .docx.")
    data = await request.body()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="Файл больше 20 МБ.")
    try:
        text = docx_to_text(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"text": text}


@app.post("/api/rewrite")
async def rewrite(payload: RewriteRequest, request: Request) -> StreamingResponse:
    style = get_style(payload.style)
    if style is None:
        raise HTTPException(status_code=422, detail="Неизвестный стиль.")

    if _queue_full():
        raise HTTPException(status_code=429, detail=_QUEUE_FULL)
    model = await _resolve_model(payload.model) if _model_key_ok(request) else None
    terms = load_terms()

    def produce(on_progress) -> dict:
        result = rewrite_text(payload.text, style, terms, model, on_progress=on_progress)
        try:
            rewrites = add_rewrite()["rewrites"]
        except (StoreError, OSError):
            try:
                rewrites = load_stats()["rewrites"]
            except OSError:
                rewrites = 0
        return {
            "result": result,
            "segments": highlight_rewrite(payload.text, result),
            "rewrites": rewrites,
        }

    return _stream_job(
        request,
        produce,
        request_id=_job_id(payload.request_id),
        chars=len(payload.text),
    )


@app.post("/api/proofread")
async def proofread(payload: ProofreadRequest, request: Request) -> StreamingResponse:
    if _queue_full():
        raise HTTPException(status_code=429, detail=_QUEUE_FULL)
    model = await _resolve_model(payload.model) if _model_key_ok(request) else None
    terms = load_terms()

    def produce(on_progress) -> dict:
        result = proofread_text(
            payload.text,
            terms,
            grammar=payload.grammar,
            model=model,
            on_progress=on_progress,
        )
        return {
            "result": result.text,
            "segments": highlight_proofread(
                payload.text,
                result.text,
                result.uncertain,
                grammar=payload.grammar,
            ),
        }

    return _stream_job(
        request,
        produce,
        request_id=_job_id(payload.request_id),
        chars=len(payload.text),
    )


@app.get("/api/stats")
async def get_stats() -> dict[str, int]:
    return load_stats()


@app.post("/api/stats/like")
async def like_app(payload: LikeRequest) -> dict[str, int]:
    try:
        return set_app_like(payload.liked)
    except StoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/feedback", response_class=HTMLResponse)
async def feedback_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "feedback.html",
        {"model_choice": bool(_admin_key())},
    )


@app.get("/api/feedback")
async def get_feedback() -> dict:
    return {"ideas": load_ideas()}


@app.post("/api/feedback")
async def create_feedback(payload: IdeaRequest) -> dict:
    try:
        idea = add_idea(payload.name, payload.text)
    except StoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return idea


@app.post("/api/feedback/{idea_id}/like")
async def like_feedback(idea_id: str, payload: LikeRequest) -> dict:
    try:
        return set_like(idea_id, payload.liked)
    except StoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/feedback/admin")
async def feedback_admin(request: Request) -> dict[str, bool]:
    if not _model_key_ok(request):
        raise HTTPException(status_code=403, detail="Недостаточно прав.")
    return {"ok": True}


@app.delete("/api/feedback/{idea_id}")
async def remove_feedback(idea_id: str, request: Request) -> dict[str, bool]:
    if not _model_key_ok(request):
        raise HTTPException(status_code=403, detail="Недостаточно прав.")
    try:
        delete_idea(idea_id)
    except StoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
