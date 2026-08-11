# GuardianAI Backend — Railway-compatible, CPU-first production image
FROM python:3.12-slim AS runtime

# Provider/model/host allowlists are non-secret deployment policy defaults. Railway
# service variables may still override them explicitly. Credentials are never baked
# into the image and remain tenant-scoped in the configured secret store.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    STORAGE_DIR=/data/storage \
    EXTERNAL_LLM_ALLOWED_PROVIDERS=openai,anthropic,google,xai \
    EXTERNAL_LLM_ALLOWED_MODELS=openai:gpt-5.6-sol,openai:gpt-5.6-terra,openai:gpt-5.6-luna,openai:gpt-5.4,anthropic:claude-sonnet-5,anthropic:claude-opus-5,anthropic:claude-sonnet-4-6,google:gemini-3.6-flash,google:gemini-3.1-pro-preview,google:gemini-3.1-flash-lite,xai:grok-4.5,xai:grok-4.3 \
    EXTERNAL_LLM_ALLOWED_HOSTS=api.openai.com,api.anthropic.com,generativelanguage.googleapis.com,api.x.ai

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

# The same image serves the web and worker Railway services. Detect the active
# process so the web container checks HTTP while the worker checks arq's Redis
# heartbeat key.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD if tr '\0' ' ' < /proc/1/cmdline | grep -q 'app.worker.settings.WorkerSettings'; then \
            gosu guardian arq --check app.worker.settings.WorkerSettings; \
        else \
            curl -fsS "http://127.0.0.1:${PORT:-8000}/health"; \
        fi || exit 1

# DATABASE_URL must be supplied by Railway PostgreSQL. STORAGE_DIR must be below
# the attached RAILWAY_VOLUME_MOUNT_PATH; no writable SQLite fallback exists.
# Use a shell only for dynamic PORT expansion, then exec Uvicorn so SIGTERM
# reaches the server directly during zero-downtime deployments.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\" --proxy-headers --forwarded-allow-ips \"${TRUSTED_PROXY_IPS:-127.0.0.1}\""]
