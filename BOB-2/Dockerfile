# ─────────────────────────────────────────────────────────────
# GuardianAI — Multi-stage Dockerfile
# ─────────────────────────────────────────────────────────────
# Stage 1: Frontend build
# Stage 2: Backend + pre-built frontend served by FastAPI
# ─────────────────────────────────────────────────────────────

# ── Stage 1: Build the Next.js frontend ──────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python backend + static frontend ───────────────
FROM python:3.12-slim AS runtime

# System dependencies required by Tesseract OCR and PostgreSQL client
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-ara \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN groupadd -r guardian && useradd -r -g guardian -m guardian

WORKDIR /app

# Python dependencies
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Backend source
COPY backend/ ./

# Bring in the pre-built frontend
COPY --from=frontend-builder /build/frontend/.next /app/frontend/.next
COPY --from=frontend-builder /build/frontend/public /app/frontend/public

# Storage directory
RUN mkdir -p /app/storage && chown guardian:guardian /app/storage

# Switch to non-root
USER guardian

ENV PORT=8000
EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
