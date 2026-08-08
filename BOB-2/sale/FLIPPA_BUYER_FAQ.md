# Buyer FAQ — GuardianAI on Flippa

> **Pre-purchase questions most buyers ask.** Update this list after the first 10 buyer conversations.

---

## 🟢 General Questions

### Q1: What exactly am I buying?
**A:** Three things bundled together:
1. **Full source code** (FastAPI backend + Next.js frontend, ~52K LOC) on GitHub
2. **Live production deployment** on Railway (Postgres + Redis + ClamAV + 2 web services)
3. **Custom domain** `athmar-aisolution.net` (paid through Aug 2027) with DNS configured

You are NOT buying a business with customers — there are zero paying users today. You're buying **production-ready code + infrastructure** that you can either operate yourself or sell again.

### Q2: Is there any recurring revenue (MRR)?
**A:** **No.** Zero paying customers at listing time. The P3 SaaS layer (billing, signup, capabilities) is scaffolded in code but not connected to live Stripe. Anyone claiming MRR on this listing is wrong — verify via the live demo at `athmar-aisolution.net` (login screen only, no pricing/checkout pages exist).

### Q3: Can I see the product working?
**A:** Yes — three live URLs:
- `https://athmar-aisolution.net/` — login page (Arabic RTL)
- `https://app.athmar-aisolution.net/` — Next.js app shell
- `https://api.athmar-aisolution.net/health` — backend health endpoint (returns 200)

To see the **dashboard and full features**, you'll need to:
1. Clone the repo
2. Set up local dev (Postgres + Redis + Telegram env vars)
3. Run `alembic upgrade head` + seed an owner account
4. Login and explore

The seller will provide a 1-hour Loom walkthrough for serious buyers (after NDA).

---

## 🟡 Technical Questions

### Q4: What's the tech stack?
**A:**
| Layer | Stack |
|---|---|
| Backend | Python 3.11, FastAPI 0.139, SQLAlchemy 2.0, Alembic, Pydantic 2.13 |
| Auth | PyJWT, bcrypt, cryptography 49, PyOTP (MFA) |
| Database | PostgreSQL 15 |
| Cache/Queue | Redis 7 + arq workers |
| Frontend | Next.js 14, TypeScript, Tailwind, React |
| AI/ML | sentence-transformers (BGE-M3), custom name-matching |
| OCR | Tesseract (Arabic + English) |
| ERP | Odoo XML-RPC (v16-v19) |
| Infra | Railway, Docker, Cloudflare DNS |

### Q5: Is the code well-tested?
**A:** Partial. Test coverage is **moderate, not complete**:
- ✅ Pytest suite for billing, capabilities, email verification, tenant provisioning
- ✅ P3 HTTP smoke tests
- ⚠️ No end-to-end browser tests (Playwright/Cypress)
- ⚠️ Coverage reports not generated
- ⚠️ Some legacy modules under-tested

**Expect to spend 1-2 weeks writing tests before going to production-customer scale.**

### Q6: Is the security actually production-grade or just claims?
**A:** Verified security controls:
- ✅ Bcrypt password hashing
- ✅ JWT with refresh token rotation
- ✅ MFA/TOTP enforced for owner/admin
- ✅ Fernet encrypted secret store (with Azure KV option)
- ✅ Security headers middleware (CSP, HSTS, etc.)
- ✅ Request size limits
- ✅ Audit logging middleware
- ✅ Immutable audit chain (cryptographic)
- ✅ ERP outbound SSRF guard (fail-closed)
- ✅ ClamAV malware scanning for uploads
- ✅ OCR guard for document processing

**Not yet done:**
- ❌ No third-party security audit (penetration test)
- ❌ No SOC 2 / ISO 27001 certification
- ❌ Legal review of `legal/` templates pending

### Q7: Does it work with Odoo?
**A:** Yes — verified code paths for Odoo v16-v19 XML-RPC integration. Tested with `discover`, `connection`, `test-connection`, `companies`, `partners` endpoints. Live Odoo ERP is **not connected** in the current production deployment (env vars not set). You'll need your own Odoo instance to test.

### Q8: What about Telegram bot functionality?
**A:** Code exists (`telegram_bot.py`, `telegram_accounting_service.py`, `telegram_ingestion.py`). **Disabled by default** in production via `TELEGRAM_BOT_ENABLED=false`. To enable: provision a Telegram bot via BotFather, set env vars, and pass security review. Documented in `TELEGRAM_INGESTION_SECURITY.md`.

### Q9: Can it handle Arabic accounting?
**A:** Yes — built for Arabic-first accounting:
- Bilingual UI (RTL Arabic / LTR English)
- Tesseract OCR with Arabic language data
- Tests for SAR currency formatting
- Arabic name normalization in the matching engine

---

## 🔴 Pricing & Business Questions

### Q10: Why the asking price range $35k-$55k?
**A:** Three components:
- **Code value:** Comparable SaaS code-only (no MRR) on Flippa trades at $15k-$60k
- **Infrastructure:** Live Railway deployment + custom domain = ~$2k-$5k saved on setup
- **Time saved:** ~6-9 months of senior dev work to rebuild from scratch

**BUT:** No MRR is a 3-5x multiple penalty. If this had $5k MRR + 50 customers, asking price would be $150k-$250k.

### Q11: Are there any hidden costs I'm not seeing?
**A:** Yes — be aware of these ongoing costs after acquisition:
| Item | Monthly Cost |
|---|---|
| Railway (Postgres + Redis + 2 web services) | $25-$80 |
| Custom domain renewal | $11/year |
| Stripe fees (once you add it) | 2.9% + 30¢ per transaction |
| Odoo hosting (if you don't have one) | $20-$200/month |
| Email (Resend) | $0-$20/month |
| LLM API costs (Anthropic/OpenAI) | $50-$500/month depending on usage |
| DevOps/maintenance (your time or contractor) | $500-$3000/month |

**Realistic monthly burn at scale: $600-$4000/month.**

### Q12: What's the realistic time to first paying customer?
**A:** Honest estimate based on what's missing:
- 1-2 weeks: complete Stripe wiring + pricing page
- 2-3 weeks: marketing site + landing copy
- 1 week: Resend email integration
- 1-2 weeks: pilot customer onboarding flow
- 4-6 weeks: legal review + ToS/Privacy

**Total: 8-12 weeks from code-handover to first paying customer**, assuming you have sales/marketing capacity.

---

## 🟣 Transfer & Legal Questions

### Q13: How does the transfer work?
**A:** Standard Flippa escrow flow:
1. Buyer commits funds to Flippa escrow
2. Seller transfers GitHub repo ownership (or buyer forks + seller removes)
3. Seller transfers Railway project ownership (or duplicates services for buyer)
4. Seller transfers domain ownership via Cloudflare (initiate transfer, buyer accepts)
5. Seller provides credentials handover doc with all env vars
6. Buyer verifies everything in their own accounts
7. Flippa releases funds to seller

### Q14: Are there any IP/patent issues?
**A:** Not that the seller is aware of. All code is original work by the seller. Third-party dependencies are listed in `requirements.txt` and `package.json` (all permissive licenses: MIT, Apache 2.0, BSD). **The seller recommends the buyer do their own IP review before final purchase.**

### Q15: Will the seller help with onboarding?
**A:** Yes — 30 days of email support included for:
- Deployment questions
- Database schema questions
- Integration questions (Odoo, Telegram, LLM providers)
- Bug triage on existing code

**Not included:**
- Building new features
- Production customer support
- Marketing/sales help

### Q16: What if I want to rebrand to a different name?
**A:** Straightforward — search for "GuardianAI" and "BOB-2" in the codebase (about 200 occurrences across config files, README, docs). Rebrand takes 1-2 hours of search-and-replace + updating `.env.example` and frontend constants. Domain transfer is separate — buyer gets `athmar-aisolution.net` but can use any domain they own.

### Q17: Can I sell this again on Flippa later?
**A:** Legally yes, ethically should be disclosed. If you re-sell, you must disclose:
- This is a second-hand sale
- The codebase is the same
- Any modifications you've made

The seller has no objection to resale as long as the same disclosure rules are followed.

---

## 📞 Contact

For questions not covered here, contact the seller directly:
- **Email:** Moatasim1111@gmail.com
- **GitHub:** https://github.com/MoatasimFaroog1111/BOB-2
- **Listing platform:** Flippa.com (use platform messaging for sensitive questions)

*Last updated: August 2026*
