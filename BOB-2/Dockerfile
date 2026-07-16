# GuardianAI Backend — Railway-compatible, CPU-first production image
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    STORAGE_DIR=/app/storage

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-ara \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r guardian && useradd -r -g guardian -m guardian
WORKDIR /app

# The full dependency lock contains optional local embedding/transformer packages
# and multi-gigabyte CUDA artifacts. Railway only needs the web/runtime profile;
# accounting_ai.py already falls back to the deterministic CPU-safe embedding
# implementation when sentence-transformers is unavailable.
COPY backend/requirements.txt ./requirements.txt
RUN grep -vE '^(pytest|sentence-transformers|transformers)==' requirements.txt \
        > requirements.runtime.txt \
    && pip install --no-cache-dir --no-compile -r requirements.runtime.txt \
    && pip check

COPY backend/ ./

RUN python -m compileall -q app \
    && mkdir -p /app/storage \
    && chown -R guardian:guardian /app/storage \
    && chmod 750 /app/storage

USER guardian
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/health" || exit 1

# Use a shell only for Railway's dynamic PORT expansion, then exec Uvicorn so
# SIGTERM reaches the server directly during zero-downtime deployments.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\" --proxy-headers --forwarded-allow-ips \"${TRUSTED_PROXY_IPS:-127.0.0.1}\""]
