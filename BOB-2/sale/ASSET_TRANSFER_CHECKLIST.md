# Asset Transfer Checklist — GuardianAI to Buyer

> **Use this checklist during the Flippa escrow transfer.** Both parties should walk through it.

---

## 📋 Pre-Transfer (Seller)

### A. Code Preparation
- [ ] All branches up-to-date on GitHub
- [ ] No secrets (API keys, passwords) committed to git history
- [ ] Run `git log --all --oneline | grep -iE "(password|secret|key|token)"` — should return nothing sensitive
- [ ] `requirements.txt` and `package.json` have no internal/private packages
- [ ] All third-party licenses inventoried (`THIRD_PARTY_LICENSES.md` if exists)
- [ ] `.env.example` is complete and accurate (no real values)
- [ ] Remove any local-only files (e.g., `local.db`, `*.log`, `.env`)

### B. Database Preparation
- [ ] Create a sanitized database backup (no PII, no customer secrets)
- [ ] Document the schema (link to `sale/DATA_ROOM_INDEX.md`)
- [ ] List all Alembic migrations and verify `alembic upgrade head` runs cleanly
- [ ] Note any seed data the buyer will need

### C. Infrastructure Documentation
- [ ] List all Railway services and their roles
- [ ] Document all environment variables (grouped by service)
- [ ] Document any persistent volumes
- [ ] Document the ClamAV service role
- [ ] List all DNS records on Cloudflare
- [ ] Document any third-party service integrations (Anthropic, OpenAI, Resend)

### D. Legal Preparation
- [ ] Update `sale/SELLER_READINESS_CHECKLIST.md` with current status
- [ ] Prepare `legal/PRIVACY_NOTICE_TEMPLATE.md` for buyer customization
- [ ] Prepare `legal/DATA_PROCESSING_ADDENDUM_TEMPLATE.md` for buyer customization
- [ ] Confirm IP ownership (all code original by seller)

---

## 🔄 During Transfer (Day 0)

### E. Code Transfer (GitHub)
- [ ] **Option A:** Buyer forks the repo, then seller transfers ownership
- [ ] **Option B:** Seller transfers repo to buyer's GitHub account directly
- [ ] Verify buyer has admin access
- [ ] Buyer confirms `git clone` works
- [ ] Buyer runs `git log --oneline -20` to verify history integrity

### F. Infrastructure Transfer (Railway)
- [ ] **Option A:** Buyer creates Railway account, seller duplicates project to buyer's workspace
- [ ] **Option B:** Seller transfers Railway project ownership
- [ ] All 6 services running in buyer's account:
  - [ ] Postgres
  - [ ] Redis
  - [ ] BOB-2 (backend)
  - [ ] BOB FRONT END
  - [ ] ClamAV
  - [ ] Postgres-Jw6J
- [ ] Buyer verifies `https://bob-2-production.up.railway.app/health` returns 200
- [ ] Buyer verifies `https://bob-front-end-production.up.railway.app/` returns 200

### G. Domain Transfer (Cloudflare)
- [ ] Seller initiates domain transfer in Cloudflare:
  ```
  Cloudflare Dashboard → Registrar → Transfer Out
  ```
- [ ] Seller provides EPP/auth code to buyer
- [ ] Buyer accepts transfer in their Cloudflare account
- [ ] Buyer configures DNS records (or imports from seller's zone file)
- [ ] Buyer verifies DNS propagation: `dig athmar-aisolution.net`
- [ ] Buyer verifies SSL: `curl -I https://athmar-aisolution.net/`

### H. Credentials Handover
- [ ] Create `HANDOVER_CREDENTIALS.md` with ALL secrets (encrypted/secure delivery)
- [ ] Include:
  - [ ] `SECRET_KEY` (production)
  - [ ] `DATABASE_URL`
  - [ ] `REDIS_URL`
  - [ ] `ANTHROPIC_API_KEY` (if seller used this)
  - [ ] `OPENAI_API_KEY` (if seller used this)
  - [ ] `ODOO_*` (if configured)
  - [ ] `RESEND_API_KEY` (if configured)
  - [ ] Any custom API tokens
- [ ] Buyer confirms receipt and stores in their password manager
- [ ] Seller changes/rotates any shared credentials after transfer

---

## ✅ Post-Transfer Verification (Day 1-7)

### I. Code Verification
- [ ] Buyer clones fresh repo
- [ ] Buyer runs `pip install -r requirements.txt` successfully
- [ ] Buyer runs `npm ci` in frontend successfully
- [ ] Buyer runs `pytest` — all tests pass
- [ ] Buyer runs `npm run build` — frontend builds without errors
- [ ] Buyer runs `npm run lint` — no critical errors

### J. Local Deployment Test
- [ ] Buyer runs `alembic upgrade head` — migrations apply cleanly
- [ ] Buyer seeds an owner account (using `GUARDIAN_SEED_*` env vars)
- [ ] Buyer logs in via `http://localhost:3000`
- [ ] Buyer navigates dashboard, ERP module, accounting AI module

### K. Production Verification
- [ ] All 3 custom domains accessible:
  - [ ] `https://athmar-aisolution.net/`
  - [ ] `https://app.athmar-aisolution.net/`
  - [ ] `https://api.athmar-aisolution.net/health`
- [ ] SSL certificates valid (no browser warnings)
- [ ] CORS configured for new domain
- [ ] `NEXT_PUBLIC_API_BASE_URL` points to `https://api.athmar-aisolution.net`

### L. Email Support Window (30 days)
- [ ] Buyer has seller's email for support
- [ ] Seller commits to <48h response on weekdays
- [ ] Both parties agree on what "support" includes (see FAQ Q15)

---

## 🆘 Troubleshooting During Transfer

### GitHub transfer issues
- Repo has issues/PRs that buyer doesn't want? → Seller closes them before transfer
- Repo has secrets in history? → Seller uses `git filter-repo` to scrub, then force-pushes to a fresh repo
- Buyer uses GitLab/Bitbucket? → Seller pushes mirror to buyer's preferred platform

### Railway transfer issues
- Project has high monthly bill? → Seller refunds prorated amount via Flippa escrow adjustment
- Volume data is large? → Seller provides compressed backup via S3 presigned URL
- Custom plugins/extensions? → Document in `INTEGRATIONS.md`

### Domain transfer issues
- Transfer locked? → Seller unlocks in Cloudflare (Registrar → Lock status)
- 60-day transfer lock after registration? → Wait or use Cloudflare-to-Cloudflare transfer
- Buyer wants to keep domain? → Buyer registers new domain, seller redirects old one

---

## 📝 Sign-Off

**Seller:** _______________________ Date: ___________

**Buyer:** _______________________ Date: ___________

**Flippa Escrow ID:** _______________

---

*This checklist is part of the GuardianAI asset transfer package. Keep it with your sale records.*
