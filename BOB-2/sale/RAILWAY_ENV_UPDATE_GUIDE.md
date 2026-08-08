# Railway Environment Variables Update Guide

> **Status:** The DNS setup is complete and live. To make the app fully functional on the new domain, you need to update a few environment variables on Railway. This guide walks you through it step by step.

---

## 🎯 What You Need to Update

### On the **BOB-2** service (Backend)

| Variable | Current (assumed) | New Value |
|---|---|---|
| `FRONTEND_ORIGIN` | `http://localhost:3000` | `https://athmar-aisolution.net,https://app.athmar-aisolution.net` |
| `CORS_ORIGINS` | (empty) | `https://athmar-aisolution.net,https://app.athmar-aisolution.net` |
| `TRUSTED_HOSTS` | (empty) | `athmar-aisolution.net,app.athmar-aisolution.net,api.athmar-aisolution.net,bob-2-production.up.railway.app` |
| `BACKEND_HOST` | `127.0.0.1` | `0.0.0.0` (recommended for Railway) |

### On the **BOB FRONT END** service (Frontend)

| Variable | Current (assumed) | New Value |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | (empty or localhost) | `https://api.athmar-aisolution.net` |
| `PORT` | `3000` | `3000` (default) |

---

## 📋 Step-by-Step Instructions

### Step 1: Login to Railway
1. Open https://railway.app
2. Sign in to your account
3. Click on the **BOB** project

### Step 2: Update BOB-2 (Backend) Variables

1. Click on the **BOB-2** service card
2. Click on the **Variables** tab
3. Click **+ New Variable** or edit existing ones:

**Add or Update:**
```
FRONTEND_ORIGIN = https://athmar-aisolution.net,https://app.athmar-aisolution.net
CORS_ORIGINS = https://athmar-aisolution.net,https://app.athmar-aisolution.net
TRUSTED_HOSTS = athmar-aisolution.net,app.athmar-aisolution.net,api.athmar-aisolution.net,bob-2-production.up.railway.app
```

4. Click **Add** or **Save** for each
5. Railway will auto-redeploy the service

### Step 3: Update BOB FRONT END (Frontend) Variables

1. Click on the **BOB FRONT END** service card
2. Click on the **Variables** tab
3. Add or update:

```
NEXT_PUBLIC_API_BASE_URL = https://api.athmar-aisolution.net
```

4. Railway will auto-redeploy the service

### Step 4: Wait for Redeployment

- Watch the **Deployments** tab on each service
- Wait for both to show "Success" or "Active"
- This usually takes 2-5 minutes

### Step 5: Verify

Open in browser:
- https://athmar-aisolution.net/ → should show Login page
- https://app.athmar-aisolution.net/ → should show app shell
- https://api.athmar-aisolution.net/health → should return 200

Test login with seed credentials (if you have any):
- Email: `GUARDIAN_SEED_EMAIL` (your production value)
- Password: `GUARDIAN_SEED_PASSWORD` (your production value)

---

## ⚠️ Important Notes

### 1. TRUSTED_HOSTS is Required in Production
The backend has strict host validation. If `TRUSTED_HOSTS` is empty, the backend will refuse to start in production mode (`APP_ENV=production`).

### 2. FRONTEND_ORIGIN Must Use HTTPS in Production
The backend rejects HTTP origins in production. Make sure the value starts with `https://`.

### 3. NEXT_PUBLIC_API_BASE_URL Must Be Set at Build Time
Next.js inlines `NEXT_PUBLIC_*` variables at build time. If you change it, you must trigger a rebuild (Railway does this automatically when you update env vars).

### 4. CORS_ORIGINS Format
Comma-separated, no spaces, full URLs with `https://`.

---

## 🔄 Rollback Plan

If something breaks after the update:

1. Go to the service → **Variables** tab
2. Either:
   - Click the trash icon next to the variable to delete it
   - Edit it back to the previous value
3. Railway will redeploy automatically

---

## 🆘 Troubleshooting

### "CORS error in browser console"
- Check that the frontend URL is in `CORS_ORIGINS`
- Check that both URLs use `https://` (not `http://`)

### "Invalid host header"
- Add the domain to `TRUSTED_HOSTS` (comma-separated, no protocol)

### "FRONTEND_ORIGIN must use https"
- You're using `http://` instead of `https://`

### "API health returns 401"
- Expected! `/health` is a public endpoint, but most others require auth. Use a valid token to test full functionality.

---

*Last updated: August 2026*
