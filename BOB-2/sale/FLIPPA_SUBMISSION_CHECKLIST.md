# Flippa Submission Checklist — Pre-Launch

> **Use this checklist the day you submit your listing.** Catches the most common reasons Flippa rejects or downgrades listings.

---

## ✅ Pre-Submission (One Week Before)

### Asset Preparation
- [ ] GitHub repo is public OR buyer-access-ready (transfer process documented)
- [ ] All commits pushed to `main` and `feature/saas-readiness` branches
- [ ] No secrets in git history (`git log --all | grep -iE "(password|secret|key|token)"` returns clean)
- [ ] README.md is up to date with current state
- [ ] LICENSE file is present and correct
- [ ] `.env.example` is complete (no real values)

### Production Verification
- [ ] All 3 domains responding HTTP 200:
  - [ ] https://athmar-aisolution.net/
  - [ ] https://app.athmar-aisolution.net/
  - [ ] https://api.athmar-aisolution.net/health
- [ ] SSL certificates valid (no browser warnings)
- [ ] No 500 errors in Railway logs (check last 7 days)

### Documentation
- [ ] `sale/FLIPPA_LISTING_DRAFT.md` reviewed and finalized
- [ ] `sale/FLIPPA_BUYER_FAQ.md` reviewed and added to listing
- [ ] `sale/SELLER_READINESS_CHECKLIST.md` reviewed
- [ ] `sale/DATA_ROOM_INDEX.md` reviewed
- [ ] `sale/ASSET_TRANSFER_CHECKLIST.md` reviewed

---

## 📸 Screenshots Required (Capture Before Submitting)

> ⚠️ **You need these before submitting.** Captured from the LIVE production deployment.

### 1. Login Page (Public)
- **URL:** https://athmar-aisolution.net/
- **What to capture:** Full page, Arabic RTL, dark theme
- **File name:** `01-login-page.png`
- **Recommended size:** 1920x1080 or 1440x900

### 2. Signup Page (Public)
- **URL:** https://athmar-aisolution.net/ → click "إنشاء حساب جديد"
- **What to capture:** Invite-only signup form
- **File name:** `02-signup-page.png`

### 3. Dashboard (Requires Owner Account)
- **URL:** After logging in with seed credentials
- **What to capture:** Main dashboard, navigation menu
- **File name:** `03-dashboard.png`

### 4. Accounting AI Module
- **URL:** /accounting-ai in the app
- **What to capture:** OCR upload interface or results
- **File name:** `04-accounting-ai.png`

### 5. ERP Connection Screen
- **URL:** /erp or /settings/accounting-systems
- **What to capture:** Odoo connection form
- **File name:** `05-erp-connection.png`

### 6. API Health Check (Terminal)
- **Command:** `curl -i https://api.athmar-aisolution.net/health`
- **What to capture:** Terminal showing HTTP 200 response
- **File name:** `06-api-health-curl.png`

### 7. Cloudflare DNS Records
- **URL:** https://dash.cloudflare.com → DNS → Records
- **What to capture:** List showing 3 CNAME + 3 TXT
- **File name:** `07-cloudflare-dns.png`

### 8. Railway Services
- **URL:** https://railway.app/project/YOUR-PROJECT-ID
- **What to capture:** All 6 services showing "Active" status
- **File name:** `08-railway-services.png`

### 9. GitHub Repository
- **URL:** https://github.com/MoatasimFaroog1111/BOB-2
- **What to capture:** Repository main page showing branches and commit history
- **File name:** `09-github-repo.png`

### 10. Code Architecture Diagram (Optional but Impressive)
- **What to capture:** A diagram showing backend, frontend, database, ERP integration
- **File name:** `10-architecture.png`
- **Tool suggestion:** draw.io, Excalidraw, or Mermaid in a Markdown file

---

## 📝 Flippa Listing Form Fields

When you submit, you'll need:

### Title (60 chars max)
```
GuardianAI — Enterprise AI Accounting SaaS (Production Live)
```

### Subtitle/Tagline (155 chars max)
```
Production-deployed AI accounting & ERP automation. ~52K LOC, Odoo integration, multi-tenant, MFA, audit chain. Live on Railway.
```

### Category
- **Primary:** SaaS (Software as a Service)
- **Secondary:** Business → Accounting & Finance
- **Industry:** B2B SaaS, Enterprise Software

### Asking Price
```
$45,000 (or your chosen price in the $35k-$55k range)
```
- Set "OR Best Offer" to enable negotiation
- Set reserve price (suggested: $30,000)

### Monetization
- **Type:** Code + Infrastructure (Asset Sale)
- **NOT:** Revenue-generating SaaS (be honest!)

### Listing Type
- **Auction:** 7 days (recommended for SaaS)
- **OR Buy It Now:** with "Make Offer" option

### Description
- Use `sale/FLIPPA_LISTING_DRAFT.md` content
- Paste as Markdown — Flippa supports it

### Tags
- AI
- SaaS
- Accounting
- ERP
- Odoo
- OCR
- Arabic
- Multi-tenant
- B2B
- Enterprise

---

## ⚠️ Honest Disclosures (Required by Flippa)

In the description or dedicated field:

1. **No paying customers at time of listing**
2. **No MRR or revenue figures**
3. **Invite-only signup (admin-controlled, by design)**
4. **Buyer needs to complete Stripe integration + marketing site**
5. **Legal documents are templates pending review**
6. **No third-party security audit completed**

These are NOT weaknesses to hide — they're part of the asset profile.

---

## 💡 Listing Optimization Tips

### 1. Use the Headline Formula
- Outcome-led: "X for Y so they can Z"
- Example: "AI accounting automation for finance teams so they can close books in days, not weeks"

### 2. First 3 Lines Matter Most
Buyers see the first 3 lines above the fold. Lead with:
- What it is
- What's live now
- What buyer gets

### 3. Use Bullet Points
Scannable lists outperform paragraphs. Use ✓ checkmarks for completed items.

### 4. Include Live Links
- Domain demo: https://athmar-aisolution.net
- GitHub: https://github.com/MoatasimFaroog1111/BOB-2
- These prove the asset is real

### 5. Be Specific About Tech Stack
Buyers are technical — they want exact versions, not vague claims.

### 6. Show the Code Architecture
A diagram beats 1000 words of description.

---

## 🚫 Things NOT to Include

- ❌ "100% complete, ready to sell" (it's not — be honest)
- ❌ Specific MRR claims (zero, so don't invent)
- ❌ Customer logos (none exist)
- ❌ Screenshots with PII (use a sanitized database)
- ❌ Promises of post-sale support beyond what's documented

---

## 📋 Submission Day Checklist

### 30 minutes before
- [ ] Take fresh screenshots (avoid showing outdated UI)
- [ ] Verify all 3 domains are still responding 200
- [ ] Have `sale/FLIPPA_LISTING_DRAFT.md` and `sale/FLIPPA_BUYER_FAQ.md` open in tabs
- [ ] Flippa account is in good standing (no policy violations)

### During submission
- [ ] Copy title from template
- [ ] Copy subtitle from template
- [ ] Paste description (Markdown supported)
- [ ] Upload all 10 screenshots in order
- [ ] Set category and tags
- [ ] Set price and reserve
- [ ] Add honest disclosures
- [ ] Preview listing
- [ ] Submit

### After submission
- [ ] Share listing URL with trusted network for review
- [ ] Respond to buyer questions within 24 hours
- [ ] Don't change price for first 48 hours (looks desperate)
- [ ] Prepare credentials handover doc in advance

---

## 🆘 If Flippa Rejects the Listing

Common reasons and fixes:

| Reason | Fix |
|---|---|
| "Insufficient proof of asset" | Add more screenshots, especially dashboard |
| "Vague revenue claims" | Remove any MRR mentions (you have none anyway) |
| "Missing disclosures" | Add honest disclosures section |
| "Suspicious activity" | Verify your Flippa account is verified with ID |
| "Code doesn't match description" | Make sure GitHub repo is public and matches |

Contact Flippa support if rejected — they usually tell you exactly what to fix.

---

*Last updated: August 2026*
