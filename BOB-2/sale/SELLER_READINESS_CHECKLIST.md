# Seller Readiness Checklist

Audit snapshot: 2026-08-03

## Current decision

**Status: technically demonstrable, but not yet ready to publish as a verified sale listing.**

The core application is substantial and testable. The remaining blockers are mainly ownership, commercial evidence, production access, legal review, and buyer-facing documentation. Do not claim revenue, customers, ZATCA certification, completed accounting UAT, or legal approval without evidence.

## Verified in this audit

- [x] Public source repository is accessible and has a proprietary top-level license notice.
- [x] Main application is under `BOB-2/` with a FastAPI backend and Next.js frontend.
- [x] Backend baseline: **452 passed, 4 skipped** (pytest, Python 3.12, runtime dependency set), including replacement PDF/OCR/parser and configuration-only CORS regressions.
- [x] Frontend production build completes successfully after removing the unused legacy static frontend from `frontend/public/`.
- [x] Frontend unit tests: **5 passed** (vitest); TypeScript `tsc --noEmit` is clean.
- [x] Frontend lint has **0 errors**; 51 warnings remain as quality debt.
- [x] CI enforces frontend lint, typecheck, unit tests, and production build (typecheck and unit tests added 2026-08-04).
- [x] Production backend returned HTTP 200 from `/health` and `/ready`; database, Redis, and storage reported ready.
- [x] GitHub production monitoring was repaired by configuring `PRODUCTION_BACKEND_URL`; manual workflow run `30792670664` succeeded.
- [x] Current dependency manifests contain no PyMuPDF/MuPDF runtime dependency.
- [x] CycloneDX 1.6 inventories cover the lightweight Python production manifest, all 98 pinned components in the full backend lock (including optional ML/development packages), and a closed npm production dependency graph.
- [x] Current production-runtime and full-backend-lock `pip-audit` reports plus production `npm audit` found 0 known dependency vulnerabilities; the container image and future advisories are outside those reports.
- [x] Production CORS origins are configuration-only; the seller-specific Railway frontend origin was removed from source code.
- [x] Backend tests force Hugging Face/Transformers offline and redirect model caches to temporary storage, preventing multi-gigabyte CI downloads.
- [x] Security-focused tests and workflows exist for tenant isolation, authorization, monetary integrity, immutable audit history, external LLM policy, Telegram controls, and ERP outbound restrictions.

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
