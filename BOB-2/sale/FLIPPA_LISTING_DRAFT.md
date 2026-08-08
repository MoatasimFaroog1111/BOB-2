# GuardianAI Accountant & Auditor Enterprise — Flippa Listing Draft

> **Status:** Production-deployed, live on Railway. End-to-end verified August 2026.
> **Brand:** Currently sold as **"GuardianAI"** (internal codename: BOB-2).
> **Marketplace:** Flippa.com
> **Listing type:** SaaS asset sale (code + infrastructure + customer contracts)

---

## 🚀 Headline (Option A — outcomes-led)

> **Enterprise-grade AI accounting & ERP automation platform — production-deployed, audited, and shipping. Built for accounting firms and finance teams that need AI-assisted journal entries, bank reconciliation, document OCR, and multi-tenant ERP control — without building from scratch.**

---

## 📋 Short Description (155 chars max)

```
Production AI accounting SaaS: OCR invoices, AI journal entries, bank rec, multi-tenant Odoo. 26+ API endpoints, ~52K LOC, live on Railway.
```

---

## 🎯 Long Description

### What This Is

GuardianAI Accountant & Auditor Enterprise is a **production-deployed, multi-tenant SaaS platform** that automates the most painful parts of accounting work:

- **AI document matching** — invoices, receipts, vendor bills, POs, bank statements, journal entries, trial balances
- **AI-drafted journal entries** with confidence scores, explanations, and human-in-the-loop approval (no automatic ERP posting)
- **Bank reconciliation** with hard-coded audit rules and a hardened reconciliation pipeline
- **Multi-tenant Odoo ERP integration** via XML-RPC (v16 → v19)
- **Document OCR** with Arabic + English support
- **Bilingual UI** (Arabic RTL / English LTR)
- **Enterprise RBAC** — Owner, Admin, Accountant, Auditor, CFO, Viewer
- **MFA + JWT + Fernet secret store** + immutable audit chain + Telegram ingestion (off by default)

### What's Already Built (Live in Production)

- **Backend:** FastAPI + Python 3.11, **~30,000 LOC** across 26 API modules
- **Frontend:** Next.js 14 + TypeScript, **~22,000 LOC**
- **Infrastructure:** PostgreSQL 15, Redis 7, ClamAV malware scanning, Arq background workers — all running on Railway
- **Custom domain:** `athmar-aisolution.net` (DNS + Let's Encrypt SSL live)
- **26+ production API endpoints**, 13+ database migrations, complete test suite
- **Production-grade security:** bcrypt, PyJWT, cryptography 49, MFA (TOTP), encrypted secret store with Azure KV support, security headers middleware, request size limits, audit middleware, RBAC enforcement

### What's NOT Built (Honest Disclosure)

This is a **production-grade platform, not a finished SaaS business**. To launch as a paying SaaS the buyer needs to add:

- ❌ **Payment integration** — Stripe/billing is scaffolded (`billing/in_memory_provider.py`) but no live Stripe keys wired. Frontend has no pricing page or checkout.
- ❌ **Self-service signup** — current flow is **invite-only** by design (admin-controlled, common for B2B accounting). The P3 SaaS layer adds a signup API (`/api/v1/signup`) but no live Stripe checkout behind it.
- ❌ **Marketing site & landing copy** — the only public page right now is the login screen at `athmar-aisolution.net/`
- ❌ **Verified MRR / customer logos** — zero paying customers at time of listing. Sales materials (`sale/` folder) are draft-stage.
- ❌ **Email delivery** — Resend SMTP keys not configured for production invites/password resets

**This is best positioned as a buy-and-flip OR buy-and-operate enterprise target.** The buyer inherits a working product, not a paying SaaS business.

### What the Buyer Gets

| Asset | Description |
|---|---|
| **Full source code** | GitHub repo: `MoatasimFaroog1111/BOB-2` — `main` + `feature/saas-readiness` branches |
| **Production deployment** | Live on Railway project `BOB` (Postgres, Redis, ClamAV, BOB-2 backend, BOB FRONT END) |
| **Custom domain** | `athmar-aisolution.net` (paid through 2027) with DNS configured |
| **3 production URLs** | `athmar-aisolution.net` (landing), `app.athmar-aisolution.net` (app), `api.athmar-aisolution.net` (API) |
| **Documentation** | `sale/` folder has: ACQUIRE listing draft, SELLER_READINESS_CHECKLIST, DATA_ROOM_INDEX, SECURITY_DEPLOYMENT.md, IMMUTABLE_AUDIT_CHAIN.md, ERP_OUTBOUND_SECURITY.md, EXTERNAL_LLM_SECURITY.md, RAILWAY_CLAMAV_RELEASE_GATE.md, MONETARY_INTEGRITY.md |
| **Database schema** | 17+ Alembic migrations covering core tables, MFA, audit chain, encrypted secrets, tenant offboarding, OCR reconciliation, immutable audit |
| **Test coverage** | Pytest suite covering billing, capabilities, email verification, tenant provisioning, P3 HTTP smoke |
| **CI/CD** | GitHub Actions: migrations, security (pip-audit), dependency-lock sync |

### Tech Stack (Buyer Should Know)

| Layer | Stack |
|---|---|
| Backend | FastAPI 0.139, SQLAlchemy 2.0, Alembic, Pydantic 2.13, PyJWT, bcrypt, cryptography, PyOTP, arq (worker), clamd, OpenAI/Anthropic LLM clients |
| Frontend | Next.js 14, TypeScript, Tailwind, React |
| Database | PostgreSQL 15 |
| Cache/Queue | Redis 7 + arq workers |
| AI/ML | sentence-transformers (BGE-M3, 1024-dim), custom name-matching trainer, deterministic embedding fallback for offline |
| OCR | Tesseract (Arabic + English) |
| ERP | Odoo XML-RPC (v16-v19) |
| Infra | Railway, Docker, Cloudflare DNS |

### Verified Live (E2E Tested Aug 6, 2026)

```
✓ https://athmar-aisolution.net/         HTTP 200  (login page, Arabic RTL)
✓ https://app.athmar-aisolution.net/      HTTP 200  (Next.js app shell)
✓ https://api.athmar-aisolution.net/health HTTP 200 (FastAPI health endpoint)
✓ /api/v1/system/status                  HTTP 401  (auth required — proves API live + protected)
✓ /api/v1/agents/capabilities            HTTP 401  (auth required — proves AI module live)
✓ /api/v1/erp/companies                  HTTP 401  (auth required — proves ERP module live)
✓ DNS: 3 CNAME + 3 TXT verification records on Cloudflare
✓ SSL: 3 Let's Encrypt certificates, all VALID + COMPLETE
✓ Railway: 6 services running (Postgres, Redis, BOB-2, BOB FRONT END, ClamAV, Postgres-Jw6J)
```

---

## 💰 Pricing Strategy

**Asking Price:** $35,000 — $55,000 USD

**Rationale:**
- Comparable Flippa listings of "AI SaaS code-only" (no MRR) in this category trade at $15k-$60k
- This listing includes **production deployment + live domain + verified uptime**, which is rare
- The codebase alone is ~52K LOC of tested, security-hardened, ERP-integrated code
- **BUT:** No MRR, no paying customers, no self-serve billing — these would otherwise justify 3-5x multiple

**Bid suggestion:** Start offers at $25k-$30k. Serious buyers will recognize the value of a working production deployment.

---

## 📸 Screenshots (Required for Flippa)

> ⚠️ **NOTE TO SELLER:** Capture these BEFORE listing:

1. **Login page** — `https://athmar-aisolution.net/` (Arabic RTL, dark theme)
2. **Signup page** — shows invite-only flow
3. **App dashboard** — after logging in with seed owner account
4. **API health endpoint** — terminal showing `curl /health` returning 200
5. **Cloudflare DNS records** — screenshot of zone showing 3 CNAME + 3 TXT
6. **Railway services** — screenshot of project showing all 6 services running
7. **GitHub repo** — screenshot showing commit history on `feature/saas-readiness` branch

---

## 🎯 Target Buyer

**Ideal buyer profile:**
- Technical founder or small team (3-8 people) with accounting/fintech background
- Wants to **launch an AI accounting SaaS in 60-90 days** without rebuilding the core
- Has access to Stripe/Lemon Squeezy account + marketing budget
- Comfortable completing the remaining ~20% (Stripe wiring, marketing site, pricing page)
- **OR:** Enterprise consulting firm that wants to deploy this as a white-label product for their clients

**NOT a fit for:**
- Buyers expecting instant MRR (this is code + infrastructure, not a business)
- Non-technical buyers (you need a developer to operate it)
- Buyers who want a "turnkey" SaaS without any integration work

---

## 📦 Transfer Process (What Happens After Sale)

1. **GitHub repo transfer** — Buyer gets full admin access to `MoatasimFaroog1111/BOB-2` (or repo is forked)
2. **Railway project handoff** — Buyer creates Railway account, seller transfers project or duplicates services
3. **Domain transfer** — `athmar-aisolution.net` transferred to buyer's Cloudflare account (or buyer keeps their own domain)
4. **Credentials handover** — via secure escrow (Flippa handles this)
5. **30 days of email support** — Seller answers technical questions about deployment, schema, integrations

---

## ⚖️ Legal & Compliance Disclosures

- This product is **not** an independently certified ZATCA e-invoicing solution
- SAP and Oracle ERP connectors are **not** built (Odoo only)
- Production financial posting requires human approval (intentional — AI drafts, humans approve)
- All data processing and DPA templates are in `legal/` folder, **not yet reviewed by a lawyer**
- The platform does not advertise any specific MRR, customer logos, or revenue figures

---

## 💡 Why I'm Selling

**Honest answer:** The platform is technically ready but the seller is shifting focus to other ventures. The code is solid, the deployment is verified, but turning it into a self-serve SaaS with paying customers requires dedicated marketing/sales effort that the seller is not positioned to provide.

---

## 📞 Contact

- **Seller:** Moatasim Faroog
- **Email:** Moatasim1111@gmail.com
- **GitHub:** https://github.com/MoatasimFaroog1111/BOB-2
- **Live demo:** https://athmar-aisolution.net (login page visible)
- **Listing agent:** TBD (Flippa will assign)

---

*This draft was generated based on verified production state as of August 6, 2026. All "✓" claims have been tested live and confirmed working. No claims about MRR, customer count, or revenue are made.*
