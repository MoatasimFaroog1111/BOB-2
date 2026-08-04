# Seller Readiness Checklist

Audit snapshot: 2026-08-04 (see [`VERIFICATION_REPORT_2026-08-04.md`](VERIFICATION_REPORT_2026-08-04.md) for raw command output)

## Current decision

**Status: technically demonstrable, but not yet ready to publish as a verified sale listing.**

The core application is substantial and testable. The remaining blockers are mainly ownership, commercial evidence, production access, legal review, and buyer-facing documentation. Do not claim revenue, customers, ZATCA certification, completed accounting UAT, or legal approval without evidence.

## Verified in this audit (re-run 2026-08-04 against commit `3ded7a3`)

- [x] Public source repository is accessible and has a proprietary top-level license notice.
- [x] Main application is under `BOB-2/` with a FastAPI backend and Next.js frontend.
- [x] Backend local suite: **275 tests passed** across `test_config`, `test_production_security_config`, `test_security_headers`, `test_request_limits`, `test_auth`, `test_account_access`, `test_financial_rbac`, `test_mfa`, `test_tenant_isolation`, `test_immutable_audit_chain`, `test_encrypted_secret_provider`, `test_monetary_integrity`, `test_erp_outbound_security`, `test_bank_reconciliation`, `test_bank_posting_idempotency`, `test_security_hardening`, `test_external_llm_security`, `test_telegram_accounting_approvals`, `test_openai_runtime_config`, `test_erp_monetary_route_replacement`, `test_runtime_storage_security`, etc. (Excludes ML/Redis/Odoo-fixture tests that require live infrastructure.)
- [x] Frontend production build completes successfully; **17 routes generated**, TypeScript clean.
- [x] Frontend lint has **0 errors**; 51 warnings remain as quality debt.
- [x] Local backend returned HTTP 200 from `/health`, `/ready`, and `/openapi.json` (75 paths). Database, Redis, and storage reported ready. `alembic upgrade head` applied all migrations to a fresh SQLite database.
- [x] Authenticated end-to-end UI/UX verified in an isolated browser session: login form → seeded owner credentials → JWT → authenticated dashboard (`مركز التحكم المالي`).
- [x] Fail-closed production security verified: app refuses to start without Redis, HTTPS, real `SECRET_STORE_PROVIDER`, ClamAV, ERP allowlist, PostgreSQL.
- [x] GitHub production monitoring was repaired earlier; manual workflow run `30792670664` succeeded (carried from previous audit).
- [x] Current dependency manifests contain no PyMuPDF/MuPDF runtime dependency.
- [x] Backend tests force Hugging Face/Transformers offline and redirect model caches to temporary storage.
- [x] Security-focused tests and workflows exist for tenant isolation, authorization, monetary integrity, immutable audit history, external LLM policy, Telegram controls, and ERP outbound restrictions.
- [ ] **NEW finding from this run:** `pip-audit -r requirements.runtime.lock --strict` reports **1 known vulnerability** in `cryptography 49.0.0` (`GHSA-g6cj-pr64-35w5`, fix in `50.0.0`). The previous snapshot reported 0 known vulnerabilities; this audit observes a new advisory since then. Action item: bump pin and regenerate hash-locked files.
- [x] `npm audit --omit=dev` against the frontend lockfile reports **0 vulnerabilities**.

## P0 — required before publishing the Acquire listing

### Ownership and transaction authority

- [ ] Name the legal owner of the source code, trademarks, domains, Railway project, GitHub repository, and customer contracts.
- [ ] Replace the ambiguous `BOB-2 Contributors` copyright holder with the actual legal owner after counsel confirms the wording.
- [ ] Collect IP assignment or contribution agreements for every contributor. Git history currently shows one contributor, but legal ownership still needs written confirmation.
- [ ] Decide the sale structure: asset sale, share sale, or code/license sale.
- [ ] Confirm that the seller is authorized to transfer every included asset.

### Security and credentials

- [ ] Rotate privileged GitHub, Railway, hosting, domain, and integration credentials before closing and after granting any diligence access.
- [ ] Issue a valid Railway access token and verify access to the production project, services, variables, domains, logs, backups, and billing.
- [ ] Inventory all production secrets and prepare a transfer/rotation plan. Do not place secret values in the data room.
- [ ] Confirm no customer or production data exists in Git history, artifacts, screenshots, test fixtures, or storage exports.
- [x] Generate current Python and npm dependency vulnerability reports and retain them under `release/security/`.
- [x] Generate a complete pinned-package inventory and vulnerability report for the full backend lock, including the optional ML/development stack.
- [ ] Enrich the Python inventory with verified license metadata and dependency relationships; obtain manual license approval.
- [ ] Scan the production container image and operating-system packages; resolve critical/high findings or document accepted risk.

### Product and commercial evidence

- [x] Customer-facing frontend is reachable at `https://bob-front-end-production.up.railway.app/`.
- [ ] Prepare a sanitized buyer demo account/environment and scripted walkthrough.
- [ ] Record the product launch date, current lifecycle stage, owner hours per week, team structure, and support burden.
- [ ] Provide verified revenue, MRR/ARR, profit, expenses, growth, churn, customer count, and traffic metrics, or explicitly mark the project pre-revenue.
- [ ] Provide a requested price and explain the valuation method.
- [ ] Provide the reason for sale.
- [ ] Identify all paying customers, pilots, trials, or users and the transferability of their agreements.

### Legal and compliance

- [ ] Complete container/OS inventory, Python license metadata and dependency relationships, third-party notices, and manual license review.
- [ ] Obtain counsel review of the proprietary license, privacy notice, DPA, SaaS terms, security/support schedule, data locations, and subprocessors.
- [ ] Complete accounting UAT with an authorized finance professional or describe it as unsigned and incomplete.
- [ ] Do not claim ZATCA certification or independent e-invoicing capability; the current product is an ERP-assistance/integration system.
- [ ] Confirm Saudi PDPL and cross-border data-transfer obligations for the intended operating model.

## P1 — strongly recommended before buyer outreach

- [ ] Add a repository description, homepage, product screenshots, demo video, architecture diagram, and release notes.
- [ ] Reduce the remaining 51 frontend lint warnings, prioritizing hook dependencies and unsafe `any` types in accounting workflows.
- [x] Add dedicated regression fixtures for replacement PDF text extraction, encrypted-PDF rejection, rendered-page OCR fallback, and positional PDF bank-statement parsing.
- [ ] Add frontend component/integration tests and an end-to-end smoke test for login, document upload, analysis, review, and Odoo approval.
- [ ] Produce a reproducible production deployment runbook and disaster-recovery test report.
- [ ] Document Railway service topology: backend, worker, PostgreSQL, Redis, storage, frontend, domains, health checks, and monthly costs.
- [ ] Create a sanitized demo dataset and scripted product walkthrough.
- [ ] Document the Odoo versions and workflows actually tested against live or staging systems.
- [ ] Close or triage open issues and Dependabot pull requests before opening the buyer data room.

## P2 — valuation and presentation improvements

- [ ] Choose one consistent product name: `GuardianAI Accountant & Auditor Enterprise`, `BOB-2`, or a new transferable brand.
- [ ] Add a public marketing landing page with a clear ideal customer profile and use cases.
- [ ] Create pricing tiers and a basic go-to-market plan if the product is pre-revenue.
- [ ] Add product analytics for activation, retention, feature usage, and conversion.
- [ ] Prepare a 12-month roadmap with effort and infrastructure estimates.

## Definition of ready to publish

The listing can be published when all P0 items have evidence or are explicitly and honestly disclosed as incomplete, the seller has approved the final English listing, and no payment or public submission occurs without the seller's confirmation.
