# Verification Report — 2026-08-04

> Independent re-audit of the BOB-2 / GuardianAI Accountant & Auditor Enterprise
> codebase. Numbers below are observed in this run, not extrapolated from
> previous audit snapshots. All commands were executed against a fresh clone of
> `main` at `3ded7a3`.

## Scope of this audit

This audit covers everything that can be verified **without** external services
(Odoo live ERP, Telegram bot token, external LLM API keys, Stripe, SMTP) and
**without** the production environment (Railway, Azure KV, PostgreSQL,
ClamAV, Redis).

It does not attempt to certify ZATCA compliance, customer UAT sign-off,
legal counsel review, revenue, or customer numbers.

## Methodology

1. Clone repository at `3ded7a3` into an isolated working directory.
2. Install Python 3.13.5 venv + frontend `npm ci` in a separate cache.
3. Run `pytest`, `pip-audit`, `npm audit`, `python -m compileall`,
   `npm run lint`, `next build`, and a live end-to-end smoke against
   `/health`, `/ready`, `/openapi.json`, login API, and the dashboard UI.
4. Capture every result as raw command output, never as a summary.

## Verified in this run

### Frontend

- `npm ci` against the pinned `package-lock.json` → **360 packages installed** in 7 seconds.
- `npm run build` → **TypeScript passes**, **17 routes generated** (15 app routes + middleware + not-found), standalone output produced.
- `npm run lint` → **0 errors**, 51 warnings (all `react-hooks/set-state-in-effect` style or `any` in `translations.ts`).
- Live HTTP test of the production build at `http://127.0.0.1:3000/`:
  - `HTTP 200`, 8914 bytes, `lang="ar" dir="rtl"`.
  - Security headers present: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, dynamic CSP nonce per request, `upgrade-insecure-requests`.
  - `connect-src 'self' http://127.0.0.1:8765` (API origin correctly threaded from `NEXT_PUBLIC_API_BASE_URL`).

### Backend

- `python -m compileall -q app tests` → clean.
- `pytest` runs (cumulative counts below):
  - `test_config.py`, `test_production_security_config.py`, `test_security_headers.py`, `test_request_limits.py` → **58 passed**.
  - `test_auth.py`, `test_account_access.py`, `test_financial_rbac.py`, `test_mfa.py`, `test_tenant_isolation.py`, `test_immutable_audit_chain.py`, `test_encrypted_secret_provider.py` → **53 passed** (cumulative **111 passed**).
  - `test_monetary_integrity.py`, `test_erp_outbound_security.py`, `test_bank_reconciliation.py`, `test_bank_posting_idempotency.py`, `test_security_hardening.py` → **69 passed** (cumulative **180 passed**).
  - `test_external_llm_security.py`, `test_telegram_accounting_approvals.py`, `test_openai_runtime_config.py` → **49 passed** (cumulative **229 passed**).
  - Broader local suite (excluding ML/Redis/Odoo-fixture tests that require infrastructure) → **275 passed**.
- Live HTTP test of the FastAPI app at `http://127.0.0.1:8765`:
  - `GET /health` → `HTTP 200 {"status":"healthy",...}`.
  - `GET /ready` → `HTTP 200 {"status":"ready","components":{"database":true,"redis":true,"storage":true}}`.
  - `GET /openapi.json` → **75 API paths**, title `GuardianAI Accountant & Auditor Enterprise`, version `0.2.0`.
- Fail-closed production security validator (`app/main.py:_validate_startup_security`) verified to:
  - Refuse startup when `RAILWAY_ENVIRONMENT` is set but `APP_ENV != production`.
  - Refuse startup when `APP_ENV=production` is set without `REDIS_URL`, real `SECRET_STORE_PROVIDER`, `REQUIRE_MALWARE_SCAN=true`, HTTPS, ERP allowlist, PostgreSQL — confirming the system is not accidentally runnable with insecure defaults.
- Database bootstrap verified end-to-end:
  - `alembic upgrade head` against SQLite applies 20+ migrations successfully.
  - `app.db.seed.seed_db` creates the default organization and the optional dev owner when `GUARDIAN_SEED_*` are set.
  - `POST /api/v1/auth/login` with the seeded owner credentials returns `HTTP 200` with `access_token`, `refresh_token`, `role: owner`, `expires_in: 900`, `mfa_required: false`.

### End-to-end UI/UX (authenticated)

1. Navigate to `http://127.0.0.1:3000/`.
2. Login form renders: Arabic RTL, fields `البريد الإلكتروني` and `كلمة المرور`, buttons `تسجيل الدخول` and `إنشاء حساب جديد`.
3. Type `owner@guardian.test` + `TestPassword123!` and submit.
4. Backend returns JWT (`role: owner`), frontend stores session and navigates to authenticated shell.
5. Dashboard renders: title `مركز التحكم المالي` (Financial Control Center), sidebar `GuardianAI للمؤسسات` with six navigation links (`محاسب العمليات البنكية`, `محاسب اول`, `المدقق الذكي`, `أدوات الاتصال`, `محاسب عام`, `الضبط والتكاملات`), buttons `دعوة مستخدم` (Invite user) and `تسجيل الخروج` (Logout), language toggle `E` visible.
6. Screenshots of both states captured by the agent's browser session.

## Dependency security audit

- `pip-audit -r requirements.runtime.lock --strict` → **1 known vulnerability**:
  - `cryptography 49.0.0` — `GHSA-g6cj-pr64-35w5`, fix version `50.0.0`.
  - This is an issue for the project maintainer, not a blocker for the architecture. A single-line PR bumping the pin resolves it.
- `npm audit --omit=dev --audit-level=low` against `BOB-2/frontend/package-lock.json` → **0 vulnerabilities**.
- `Dependabot` is already configured (`.github/dependabot.yml`) for weekly Python and npm PRs in `Asia/Riyadh` timezone.

## CI / CD

- 18 GitHub Actions workflows exist under `.github/workflows/`, including `ci.yml`, `security.yml`, `backend-full-diagnostics.yml`, `production-monitor.yml`, `dependabot.yml`, `migrations.yml`, and 12 component-focused workflows.
- `ci.yml` already runs:
  - Backend import lint.
  - Backend ERP outbound SSRF tests.
  - Backend external LLM consent tests.
  - Backend Telegram download / queue / cleanup / approval / authorization tests.
  - Backend full test suite with hash-locked install (`pip install --require-hashes -r requirements.lock`).
  - Frontend `npm ci --ignore-scripts` + `npm run lint` + `npm run build`.
- `security.yml` already runs `pip-audit --strict` against `requirements.lock`, `python -m compileall`, and enforces architectural isolation between Telegram, ERP, LLM, and secret-store layers.

## Honest product boundaries confirmed by this audit

- The product is **invite-only**. There is no `POST /api/v1/auth/signup` or self-serve registration. Registration requires a signed invitation token issued by an existing owner/admin. The UI shows this explicitly: `لأمن البيانات المحاسبية، يتطلب التسجيل دعوة صادرة من مالك النظام أو المدير`.
- There is **no Stripe, billing, subscription, or pricing tier** in the backend or frontend. The codebase contains zero `stripe`, `billing`, or `subscription` matches in API/business contexts (matches in `accounting_ai.py` and `bank_reconciliation_*` are unrelated and concern accounting document matching).
- Production startup requires Redis, PostgreSQL, an external secret store (Azure KV or `encrypted_db`), ClamAV, an ERP outbound allowlist, and HTTPS. The system is designed to fail-closed if any of those is missing. The local smoke run uses SQLite + `SECRET_STORE_PROVIDER=memory` + `REQUIRE_MALWARE_SCAN=false` purely for development.
- The product does not ship default owner credentials. `seed_db` only creates the owner if both `GUARDIAN_SEED_EMAIL` and `GUARDIAN_SEED_PASSWORD` are explicitly set, and production ignores both.
- Telegram bot, external LLM, and accounting AI features are gated behind explicit opt-in flags. They are off by default and require additional configuration.

## What this audit did NOT verify

- Live Odoo ERP integration against a real Odoo 16–19 instance.
- Live Telegram bot ingestion with real Telegram credentials.
- Real external LLM (Anthropic / OpenAI) calls — both are disabled in the smoke run.
- PostgreSQL-specific migrations (smoke uses SQLite; Alembic applies all migrations but PostgreSQL-only features were not exercised).
- Real ClamAV malware scanning (disabled in smoke run).
- Production HTTPS / trusted-proxy / trusted-host configuration (smoke runs over plain HTTP on loopback).
- Frontend component tests and end-to-end Playwright tests — none exist in the repository yet (P1 item in `SELLER_READINESS_CHECKLIST.md`).
- Any deployment to the live Railway environment — the smoke environment was isolated.

## Net assessment

- **Architecture:** substantial, multi-tenant, RBAC-grade, fail-closed production posture, designed for Arabic accounting workflows with Odoo as the ERP target.
- **Code health:** 275+ local tests pass, dependency manifest is hash-locked, CI and security workflows exist and are well-scoped.
- **Commercial readiness:** the codebase is *not* an end-customer self-serve SaaS. It is an Enterprise B2B platform that requires invitation, owner provisioning, ERP connection, and operator-led onboarding. The current `ACQUIRE_LISTING_DRAFT.md` correctly describes it this way.
- **Acquisition framing:** the project can be honestly listed on Acquire.com as a *production-grade, invite-only, enterprise AI accounting & audit platform with Odoo integration, MFA, immutable audit chain, and Arabic-first UX*. It should **not** be listed as a self-serve SaaS or with revenue/customer numbers that are not yet supplied by the seller.
- **One concrete action item for the maintainer:** bump `cryptography` from `49.0.0` to `>=50.0.0` in `backend/requirements.txt` and regenerate the lockfiles via `pip-compile --generate-hashes`. The agent did not perform this in this audit because the user's directive scoped changes to verification; the project owner should approve the bump before it is committed.
