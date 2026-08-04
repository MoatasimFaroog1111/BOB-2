# Acquire Listing Draft

> Draft only. Financial, user, customer, and valuation fields must be completed by the owner and verified before publication.

## Category

SaaS / AI / Fintech / Accounting Automation / ERP Integration

## One-line pitch

A bilingual, enterprise-focused AI accounting and audit platform that helps finance teams process documents, reconcile transactions, review journal-entry suggestions, and execute human-approved workflows in Odoo.

## Short description

GuardianAI Accountant & Auditor Enterprise (working repository name: BOB-2) is a bilingual Arabic/English SaaS platform for accounting assistance, audit workflows, document processing, and ERP integration. The product combines OCR, accounting-aware matching, bank reconciliation, role-based approvals, immutable audit evidence, and Odoo connectivity in a multi-tenant architecture. Finance teams can upload invoices, receipts, vouchers, and bank statements; review extracted data and AI-assisted matches; prepare journal-entry suggestions; and require authorized human approval before financial posting. The system includes a FastAPI backend, a Next.js interface, PostgreSQL, Redis-backed workers, tenant isolation, encrypted credential handling, and production-oriented security controls. It is positioned as an assistant for authorized finance professionals, not as a replacement for accounting judgment or an independently certified ZATCA e-invoicing solution.

## Product highlights

- Arabic RTL and English LTR user experience.
- OCR-assisted processing for invoices, receipts, vouchers, and bank statements.
- Accounting-aware document classification, matching, and journal-entry suggestions.
- Odoo ERP discovery, reconciliation, and human-approved posting workflows.
- Bank reconciliation with duplicate and idempotency controls.
- Multi-tenant RBAC for owners, administrators, accountants, auditors, CFOs, and viewers.
- Immutable audit-chain controls and attributable review/approval events.
- Encrypted tenant credential architecture and external LLM consent policies.
- Telegram-assisted workflows with tenant authorization and approval controls.
- Background processing with Redis/ARQ and PostgreSQL persistence.

## Target customers

- Accounting and bookkeeping firms serving Arabic-speaking businesses.
- SMEs and multi-company groups using Odoo.
- Finance teams that need document intake, reconciliation, approval, and audit evidence.
- ERP implementers seeking an accounting AI and workflow layer for Odoo deployments.

## Technology

- Backend: Python, FastAPI, SQLAlchemy, Alembic, Pydantic.
- Frontend: Next.js, React, TypeScript, Tailwind CSS.
- Data and jobs: PostgreSQL, Redis, ARQ.
- Documents: Tesseract OCR, pypdf, pdfplumber, pypdfium2, Pillow, openpyxl.
- Security: JWT, bcrypt, MFA/TOTP, encrypted secret providers, tenant-scoped RBAC.
- Deployment: Docker, Railway configuration, GitHub Actions.
- Integrations: Odoo XML-RPC, optional external LLM providers, Telegram.

## Verified technical evidence

- Backend test suite: **452 passed, 4 skipped** (pytest, Python 3.12, runtime dependency set), covering authentication, MFA, tenant isolation, monetary integrity, ERP outbound SSRF policy, immutable audit chain, Telegram authorization/approval boundaries, and worker contracts.
- Frontend unit tests: **5 passed** (vitest). TypeScript `tsc --noEmit`: **clean**. Production `next build`: **succeeds** (15 routes).
- Frontend lint: **0 errors**; 51 warnings remain as disclosed quality debt.
- Continuous integration enforces backend full tests, eight isolated backend security suites, and frontend lint, typecheck, unit tests, and production build.

- Next.js production build completed successfully.
- Live production probes (2026-08-04): backend `GET /health` returned HTTP 200 (`healthy`) and `GET /ready` returned HTTP 200 with `database`, `redis`, and `storage` all true; the frontend origin returned HTTP 200. Railway `production` environment reports SUCCESS deployments for both the backend and frontend services.
- GitHub production-monitor workflow succeeded after configuration repair.
- Full pinned backend lock audit: 96 auditable packages, including the optional ML/development stack, with 0 known findings at the audit snapshot.
- Production npm audit: 0 known findings at the audit snapshot.

## Honest product boundaries

- Financial posting requires authorized human approval and customer UAT.
- Odoo is the current production ERP target; SAP and Oracle connectors are not represented as production-ready.
- The product is not independently ZATCA certified and does not currently issue ZATCA e-invoices itself.
- Legal templates exist but are not executed agreements or legal approval.
- Revenue, customer adoption, valuation, and operating-cost claims are not yet supplied.

## Owner fields required

- Legal seller and asset owner: **TBD**
- Product name included in sale: **TBD**
- Customer-facing URL: `https://bob-front-end-production.up.railway.app/` (live login page verified; demo credentials not yet provided)
- Launch date: **TBD**
- Location: **TBD**
- Business model and pricing: **TBD**
- Users / paying customers: **TBD**
- MRR / ARR / trailing-12-month revenue: **TBD**
- Trailing-12-month profit and monthly expenses: **TBD**
- Growth and churn: **TBD**
- Owner hours per week and team: **TBD**
- Reason for sale: **TBD**
- Asking price and valuation rationale: **TBD**
- Assets included in sale: **TBD**
