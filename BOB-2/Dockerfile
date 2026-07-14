# GuardianAI Backend — hash-locked, non-root production image
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
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

COPY backend/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --no-compile --require-hashes -r requirements.lock

COPY backend/ ./

RUN mkdir -p /app/storage \
    && chown -R guardian:guardian /app/storage \
    && chmod 750 /app/storage

USER guardian
EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Proxy headers are accepted only from explicitly trusted direct peers. When the
# variable is empty, Uvicorn trusts localhost only; the application independently
# validates X-Forwarded-For against TRUSTED_PROXY_IPS.
CMD uvicorn app.main:app \
    --host 0.0.0.0 \
    --port ${PORT} \
    --proxy-headers \
    --forwarded-allow-ips "${TRUSTED_PROXY_IPS:-127.0.0.1}"
