# GuardianAI Backend — Railway-compatible, CPU-first production image
FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    STORAGE_DIR=/data/storage

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-ara \
        libpq5 \
        curl \
        gosu \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r guardian && useradd -r -g guardian -m guardian
WORKDIR /app

# Railway installs only the reviewed CPU-safe runtime profile. Every transitive
# dependency and artifact hash is fixed by pip-compile.
COPY backend/requirements.runtime.lock ./requirements.runtime.lock
RUN pip install --no-cache-dir --no-compile --require-hashes \
        -r requirements.runtime.lock \
    && pip check

COPY backend/ ./
COPY docker-entrypoint.sh /usr/local/bin/guardian-entrypoint

RUN python -m compileall -q app \
    && chmod 0755 /usr/local/bin/guardian-entrypoint

ENTRYPOINT ["/usr/local/bin/guardian-entrypoint"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/health" || exit 1

# DATABASE_URL must be supplied by Railway PostgreSQL. STORAGE_DIR must be below
# the attached RAILWAY_VOLUME_MOUNT_PATH; no writable SQLite fallback exists.
# Use a shell only for dynamic PORT expansion, then exec Uvicorn so SIGTERM
# reaches the server directly during zero-downtime deployments.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\" --proxy-headers --forwarded-allow-ips \"${TRUSTED_PROXY_IPS:-127.0.0.1}\""]