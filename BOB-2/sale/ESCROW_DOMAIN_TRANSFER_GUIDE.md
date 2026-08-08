# Escrow & Domain Transfer Guide

> **Step-by-step guide for the seller to safely hand over the GuardianAI asset via Flippa escrow and Cloudflare domain transfer.**

---

## 🔒 Part 1: Flippa Escrow Process

### How Flippa Escrow Works

1. **Buyer commits funds** to Flippa's escrow account
2. **Seller transfers assets** (code, infrastructure, domain)
3. **Buyer verifies** everything works in their own accounts
4. **Buyer releases escrow** to seller (or Flippa auto-releases after inspection period)

The inspection period is usually **3-7 days** depending on Flippa tier.

---

### 📋 Seller's Escrow Checklist

#### Before Buyer Commits Funds
- [ ] GitHub repo is ready for transfer
- [ ] Railway project is documented (services, env vars)
- [ ] Cloudflare domain is unlocked for transfer
- [ ] `HANDOVER_CREDENTIALS.md` template prepared (don't fill yet!)
- [ ] Backup of database (sanitized, no PII) ready

#### Day of Sale
- [ ] Buyer has committed funds (Flippa confirms via email/dashboard)
- [ ] Get buyer's:
  - [ ] GitHub username
  - [ ] Email for Cloudflare transfer
  - [ ] Railway email (must match account holder)
- [ ] Initiate GitHub transfer (see Part 2)
- [ ] Initiate Cloudflare domain transfer (see Part 3)
- [ ] Prepare Railway project for transfer (see Part 4)

#### During Inspection Period (3-7 days)
- [ ] Stay available for buyer's questions (<24h response)
- [ ] Don't change any production state
- [ ] Help buyer verify everything works

#### After Inspection Period
- [ ] Flippa releases funds to your account
- [ ] Stripe/paypal deposit arrives in 2-5 business days
- [ ] Confirm receipt with buyer

---

## 📦 Part 2: GitHub Repository Transfer

### Option A: Direct Transfer (Recommended for Clean Repo)

```
1. Open: https://github.com/MoatasimFaroog1111/BOB-2/settings
2. Scroll to "Danger Zone"
3. Click "Transfer ownership"
4. Enter buyer's GitHub username
5. Confirm the new repository name (e.g., buyer/BOB-2)
6. Type the repository name to confirm
7. Click "I understand, transfer this repository"
```

**What happens:**
- Repo disappears from your account
- Appears in buyer's account
- All stars, watchers, issues transfer
- Your local git remote needs updating:
  ```bash
  git remote set-url origin https://github.com/BUYER/BOB-2.git
  ```

### Option B: Buyer Forks First

```
1. Buyer forks: https://github.com/MoatasimFaroog1111/BOB-2
2. You add buyer as a collaborator with admin access
3. After buyer verifies fork works, you delete your repo
4. Buyer renames their fork to the original name
```

**Best for:** When buyer wants to keep their fork private before sale.

### Option C: Mirror Transfer (For Other Platforms)

```bash
# Mirror to buyer's GitLab/Bitbucket
git clone --bare https://github.com/MoatasimFaroog1111/BOB-2.git
cd BOB-2.git
git push --mirror https://gitlab.com/BUYER/BOB-2.git
```

**Best for:** Buyer prefers GitLab or Bitbucket.

---

## 🌐 Part 3: Cloudflare Domain Transfer

### Step 1: Prepare the Domain for Transfer

```
1. Login to Cloudflare: https://dash.cloudflare.com
2. Select the domain: athmar-aisolution.net
3. Go to: Registrar → Configuration
4. Ensure "Transfer Lock" is OFF (if ON, unlock first)
5. Get the EPP/Auth Code:
   - Click "Get code" or "Transfer"
   - Copy the auth code (typically 16+ characters)
6. Provide the auth code to buyer via Flippa messaging
```

### Step 2: Buyer Initiates Transfer

**If buyer uses Cloudflare:**
```
1. Buyer creates Cloudflare account (if not already)
2. Buyer adds athmar-aisolution.net to their account
3. Buyer selects "Transfer" instead of "Add"
4. Buyer enters the auth code you provided
5. Buyer pays the transfer fee (~$10-25 for .net)
6. Transfer completes in 1-7 days
```

**If buyer uses another registrar (Namecheap, GoDaddy, etc.):**
```
1. Buyer initiates transfer at their preferred registrar
2. Buyer enters the auth code
3. Buyer pays transfer fee
4. Transfer completes in 1-7 days
5. Cloudflare sends confirmation email to admin email on file
```

### Step 3: DNS Records Migration

After transfer, buyer needs to re-add DNS records:

```bash
# Option 1: Buyer exports DNS zone file from Cloudflare
# Cloudflare Dashboard → DNS → Export

# Option 2: Buyer re-creates manually (you provide list):
CNAME  athmar-aisolution.net              → bob-front-end-production.up.railway.app
CNAME  app.athmar-aisolution.net          → bob-front-end-production.up.railway.app
CNAME  api.athmar-aisolution.net          → bob-2-production.up.railway.app
TXT    _railway-verify.athmar-aisolution.net → railway-verify=3410ec8a...
TXT    _railway-verify.app.athmar-aisolution.net → railway-verify=67d53eec...
TXT    _railway-verify.api.athmar-aisolution.net → railway-verify=9bf8527e...
```

### Step 4: SSL Certificate Re-issue

After DNS migration, Railway will automatically re-issue Let's Encrypt certificates. This takes 5-30 minutes.

**Buyer verification:**
```bash
curl -I https://athmar-aisolution.net/  # Should show 200 with valid SSL
```

---

## 🚂 Part 4: Railway Project Transfer

### Option A: Duplicate Project (Recommended)

```
1. Seller: In Railway Dashboard, export project as JSON
   - Settings → Danger Zone → Export Project
2. Seller: Provide the JSON to buyer
3. Buyer: Creates new Railway account (or uses existing)
4. Buyer: Imports the JSON via "Import Project"
5. Buyer: Re-creates environment variables (from HANDOVER_CREDENTIALS.md)
6. Buyer: Re-deploys all services
7. Buyer: Re-adds custom domains to new services
8. Buyer: Updates DNS records (if Railway IPs changed)
```

### Option B: Direct Workspace Transfer

```
1. Seller: Add buyer's Railway email as a workspace member with Admin role
2. Buyer: Accepts invitation
3. Buyer: Once accepted, seller removes themselves
4. Buyer: Now owner of the project
```

**Risk:** Buyer gets access before paying (mitigated by Flippa escrow, but trust is required).

### Option C: Manual Service Recreation

If neither A nor B works:

```
1. Seller provides full documentation of:
   - All 6 services (name, repo, branch, build command, start command)
   - All env vars (per service)
   - All volumes
   - All custom domains
2. Buyer recreates everything in their account
3. Buyer verifies all services running
```

---

## 🔑 Part 5: Credentials Handover

Create a secure document `HANDOVER_CREDENTIALS.md` with:

### Backend (BOB-2 service) Env Vars
```bash
# Production secrets — DESTROY AFTER BUYER STORES THEM
SECRET_KEY=<64-char hex from production>
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
ANTHROPIC_API_KEY=<if configured>
OPENAI_API_KEY=<if configured>
ODOO_URL=<if configured>
ODOO_DB=<if configured>
ODOO_USERNAME=<if configured>
ODOO_PASSWORD=<if configured>
RESEND_API_KEY=<if configured>
ACCOUNT_EMAIL_FROM=<if configured>
GUARDIAN_SEED_EMAIL=<if you set this>
GUARDIAN_SEED_PASSWORD=<if you set this>
```

### Frontend (BOB FRONT END service) Env Vars
```bash
NEXT_PUBLIC_API_BASE_URL=https://api.athmar-aisolution.net
```

### Railway Account Access
- **Method:** Add buyer as workspace admin (Option B above)
- **OR:** Create new credentials and hand over (less secure)

### Cloudflare Access
- **Method:** Domain transfer (Part 3)
- **NOT recommended:** Share Cloudflare account credentials

### Database Access
- **Method:** Buyer creates their own DB instance, you provide sanitized backup
- **Backup format:** `pg_dump` of production DB with all PII removed
- **Delivery:** S3 presigned URL with 7-day expiration

---

## ⚠️ Security Checklist Before Sharing Credentials

- [ ] Remove all personal info (name, phone, address) from any documents
- [ ] Use Flippa's secure messaging (NOT email or chat)
- [ ] Generate new credentials where possible (don't share your actual password)
- [ ] After transfer, rotate any credentials that were shared
- [ ] Delete `HANDOVER_CREDENTIALS.md` from your system
- [ ] Update your password manager

---

## 🆘 Troubleshooting Common Issues

### GitHub Transfer Blocked
- **Reason:** Repo has GitHub Apps installed that block transfer
- **Fix:** Remove GitHub Apps first, then transfer

### Cloudflare Transfer Locked
- **Reason:** 60-day lock after registration or last transfer
- **Workaround:** Use Cloudflare-to-Cloudflare transfer (no lock)

### Railway Duplicate Fails
- **Reason:** Project has volumes or custom plugins that don't transfer
- **Fix:** Manually recreate volumes, then duplicate

### DNS Doesn't Propagate
- **Wait:** 24-48 hours for full global propagation
- **Test:** Use `dig @1.1.1.1 athmar-aisolution.net` to test specific DNS servers

### SSL Certificate Doesn't Re-issue
- **Reason:** DNS not pointing to Railway anymore
- **Fix:** Verify DNS first, then trigger re-issue via Railway UI

---

## 📞 Support Contacts (For Buyer Reference)

| Issue | Contact |
|---|---|
| Flippa escrow | Flippa Support: https://flippa.com/help |
| Cloudflare domain | Cloudflare Support: https://support.cloudflare.com |
| Railway project | Railway Discord: https://discord.gg/railway |
| GitHub transfer | GitHub Support: https://support.github.com |
| Code questions | Seller: Moatasim1111@gmail.com (30-day window) |

---

*Last updated: August 2026*
