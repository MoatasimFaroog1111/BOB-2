# Developer Onboarding Guide

This guide gives a repeatable path for new contributors to run GuardianAI Accountant & Auditor Enterprise locally, validate changes, and understand which checks are expected before opening a pull request.

## 1. Required toolchain

- Python 3.12+
- Node.js 20+
- npm 10+
- PostgreSQL 15+ for migration/integration work
- Redis 7+ for worker/session paths
- Tesseract OCR for document scanning flows
- Optional: Docker and Docker Compose for production-like smoke testing

> The backend dependency set is intentionally pinned for Python 3.12. Python 3.11 is not a supported development runtime for backend tests.

## 2. Repository layout

- `backend/` — FastAPI backend, Alembic migrations, workers, tests, security controls, ERP adapters, and accounting AI services.
- `frontend/` — Next.js/React/TypeScript application.
- `docs/` — architectural and operational notes.
- `legal/` — customer-facing template agreements and notices.
- `release/` — SBOM and security-audit evidence for releases.
- `.github/workflows/` — CI, security, migration, tenant-isolation, and release-gate workflows.

## 3. Environment setup

From the project root:

```bash
cp .env.example .env
```

For local development keep production-only integrations disabled unless you are explicitly testing them:

```env
APP_ENV=local
SECRET_KEY=local-secret-key-for-dev-1234567890abcdef
DATABASE_URL=sqlite:///./guardianai.db
SECRET_STORE_PROVIDER=disabled
LOCAL_LLM_ENABLED=false
EXTERNAL_LLM_ENABLED=false
TELEGRAM_BOT_ENABLED=false
REQUIRE_MALWARE_SCAN=false
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Never commit `.env`, live Odoo credentials, Telegram tokens, LLM API keys, database passwords, or customer data.

## 4. Backend local run

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Useful backend checks:

```bash
cd backend
python -m compileall -q app
python -m pytest -q
pip check
```

Targeted security/regression checks frequently used by CI:

```bash
python -m pytest -q tests/test_erp_outbound_security.py
python -m pytest -q tests/test_external_llm_security.py
python -m pytest -q tests/test_tenant_isolation_completion.py tests/test_financial_rbac.py
python -m pytest -q tests/test_monetary_integrity.py
python -m pytest -q tests/test_immutable_audit_chain.py
```

## 5. Frontend local run

```bash
cd frontend
npm ci
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```

Required frontend checks before merging UI changes:

```bash
cd frontend
npm run lint
npm run build
npm audit --omit=dev
```

The lint configuration intentionally keeps React hook dependency checks enabled. The application also contains flexible ERP/accounting API payloads, so TypeScript build validation is the source of truth for those runtime shapes.

## 6. Docker Compose smoke test

The root `docker-compose.yml` is production-oriented and intentionally fail-closed. It requires strong secrets and explicit public origins/hosts. Use it for production-like smoke tests, not as a shortcut around local development configuration.

Minimum variables normally needed for a Compose smoke test:

```env
POSTGRES_PASSWORD=<strong-local-password>
REDIS_PASSWORD=<strong-local-password>
DATABASE_URL=postgresql://guardian:<url-encoded-password>@db:5432/guardianai
REDIS_URL=redis://:<url-encoded-password>@redis:6379/0
SECRET_KEY=<openssl rand -hex 64>
FRONTEND_ORIGIN=https://example.local
TRUSTED_HOSTS=example.local
TRUSTED_PROXY_IPS=127.0.0.1
NEXT_PUBLIC_API_BASE_URL=https://api.example.local
ERP_OUTBOUND_ALLOWED_HOSTS=<your-odoo-host>
AZURE_KEY_VAULT_URL=https://<vault-name>.vault.azure.net/
```

If you only need backend/frontend iteration, prefer the local commands above.

## 7. Pull request checklist

Before requesting review, include evidence for the checks relevant to your change:

- Frontend changes:
  - `npm run lint`
  - `npm run build`
- Backend changes:
  - `python -m compileall -q app`
  - targeted `pytest` suite(s)
  - `alembic upgrade head` when migrations are touched
- Dependency changes:
  - update lock files
  - run audit tooling
  - confirm `pip check` or `npm audit` as appropriate
- Security-sensitive changes:
  - document the control boundary that changed
  - add or update regression tests
  - confirm no secrets are stored in source, logs, generated artifacts, or screenshots

## 8. Common troubleshooting

### Backend dependencies fail to install

Confirm you are using Python 3.12+. The pinned numerical/ML stack is not expected to install on Python 3.11.

### Frontend cannot reach backend

Set `NEXT_PUBLIC_API_BASE_URL` to the browser-visible backend URL. In local development this is usually `http://localhost:8000`.

### Production startup refuses to boot

This is intentional fail-closed behavior. Check `SECRET_KEY`, `SECRET_STORE_PROVIDER`, `FRONTEND_ORIGIN`, trusted hosts/proxies, ERP allowlists, Redis, database URL, and malware scanning settings.

### Telegram or external LLM appears disabled

Both are disabled by default. Enable only with tenant-scoped policy, approved secret storage, and the corresponding security tests.
