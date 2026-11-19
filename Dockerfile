# ============================================================
# LLM: модель и адрес.
# LLM_BACKEND=ollama — сервер Ollama (/api/chat).
# LLM_BACKEND=llama — llama-server из образа llama-cpp-kepler:sm35 (/v1/chat/completions).
# Править можно здесь, через --build-arg при сборке
# или через -e / docker-compose при запуске (приоритет у запуска).
# ============================================================
ARG LLM_BACKEND=ollama
ARG LLM_BASE_URL=http://host.docker.internal:11434
ARG LLM_MODEL=qwen3.5:9b
ARG LLM_REWRITE_MODEL=t-tech/T-lite-it-2.1:q4_K_M
ARG LLM_PROOFREAD_MODEL=t-tech/T-lite-it-2.1:q4_K_M
ARG LLM_API_KEY=
ARG LLM_TIMEOUT=600
ARG LLM_TEMPERATURE=0.3
ARG LLM_KEEP_ALIVE=30m
ARG LLM_NUM_CTX=4096

FROM python:3.12-slim-bookworm

ARG LLM_BACKEND
ARG LLM_BASE_URL
ARG LLM_MODEL
ARG LLM_REWRITE_MODEL
ARG LLM_PROOFREAD_MODEL
ARG LLM_API_KEY
ARG LLM_TIMEOUT
ARG LLM_TEMPERATURE
ARG LLM_KEEP_ALIVE
ARG LLM_NUM_CTX

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LLM_BACKEND=${LLM_BACKEND} \
    LLM_BASE_URL=${LLM_BASE_URL} \
    LLM_MODEL=${LLM_MODEL} \
    LLM_REWRITE_MODEL=${LLM_REWRITE_MODEL} \
    LLM_PROOFREAD_MODEL=${LLM_PROOFREAD_MODEL} \
    LLM_API_KEY=${LLM_API_KEY} \
    LLM_TIMEOUT=${LLM_TIMEOUT} \
    LLM_TEMPERATURE=${LLM_TEMPERATURE} \
    LLM_KEEP_ALIVE=${LLM_KEEP_ALIVE} \
    LLM_NUM_CTX=${LLM_NUM_CTX}

WORKDIR /app

COPY vendor/wheels /tmp/wheels
COPY requirements.txt requirements.docker.txt .
RUN pip install --no-cache-dir --no-index --find-links=/tmp/wheels -r requirements.docker.txt \
    && rm -rf /tmp/wheels /root/.cache \
    && (find /usr/local/lib/python3.12 -type d -name '__pycache__' -exec rm -rf {} + || true)

COPY app ./app
COPY templates ./templates
COPY static ./static
RUN mkdir -p /app/data && printf '%s\n' '{"terms": []}' > /app/data/terms.json

EXPOSE 8181

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8181", "--loop", "uvloop", "--http", "httptools", "--workers", "1"]
