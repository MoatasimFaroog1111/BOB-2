# Auth UX & HTTP Client Refactor — Strategic Solution

> **Date:** August 2026
> **Trigger:** User reported "Failed to fetch" error on `app.athmar-aisolution.net` + missing "نسيت كلمة المرور" link in login UI.
> **Approach:** Strategic refactor following SOLID + Component design principles (not tactical workarounds).

---

## 🔍 Root Cause Analysis

### Problem 1: "Failed to fetch"
- The login page tries to POST `${API_BASE_URL}/api/v1/auth/login`
- `API_BASE_URL` is computed in `src/lib/api.ts` and falls back to `http://127.0.0.1:8000` when `NEXT_PUBLIC_API_BASE_URL` is not set
- Browsers cannot reach `127.0.0.1` from a public origin (`app.athmar-aisolution.net`)
- Result: every login attempt produces a CORS / network error before the request ever reaches the backend

### Problem 2: "Forgot Password" link missing
- The backend exposes `/api/v1/auth/password-reset/request` and `/api/v1/auth/password-reset/confirm`
- `AuthGate.tsx` already contains the full state machine for `"forgot"` and `"reset"` states with handler functions
- **But the UI in the unauthenticated branch rendered the LoginForm directly with no link to those states**
- Result: users locked out of their accounts have no in-app recovery path

### Problem 3: Architectural debt (the real strategic issue)
- `AuthGate.tsx` was 622 lines containing 4 forms, 6 handlers, a custom `window.fetch` override, and the state machine
- Every other frontend page (audit, telegram, communication-tools, …) used raw `fetch()` directly
- No single source of truth for transport concerns (auth headers, refresh, error normalization)
- This made the codebase fragile and impossible to test in isolation

---

## ✅ Strategic Solution

Three layered changes, each addressing one SOLID principle:

### Layer 1: HTTP Client Abstraction (Dependency Inversion)

**New file:** `frontend/src/lib/http-client.ts` (277 lines)

A single `ApiClient` class that:
- Builds URLs from a base + path (or accepts absolute URLs)
- Attaches `Authorization: Bearer <token>` automatically for non-public paths
- Detects 401 responses and transparently refreshes the access token once
- Normalizes FastAPI `{ "detail": ... }` errors into a typed `ApiError`
- Exposes typed convenience methods: `login()`, `verifyMfa()`, `requestPasswordReset()`, `confirmPasswordReset()`, `register()`, `request()`
- Exposes a singleton `getApiClient()` so existing call sites can adopt it incrementally

**Backward compatibility:** `requestJson()` is preserved as a thin wrapper for legacy callers.

**SOLID mapping:**
- **DIP:** Components depend on `ApiClient`, not on raw `fetch()` or on URLs.
- **SRP:** `ApiClient` handles transport only. It does not render UI or own auth state.
- **OCP:** Add new methods or behaviors (retry, telemetry, logging) without touching call sites.

### Layer 2: Auth Form Components (Single Responsibility)

The 622-line `AuthGate.tsx` was split into 6 focused files:

| File | LOC | Responsibility |
|---|---|---|
| `AuthCard.tsx` | 133 | Presentational primitives: `AuthCard`, `AuthField`, `AuthInput`, `AuthButton`, `AuthFeedback`, `AuthSecondaryAction` |
| `LoginForm.tsx` | 96 | Render + collect login inputs. Owns no transport. |
| `PasswordResetRequestForm.tsx` | 71 | Render + collect reset request input |
| `PasswordResetConfirmForm.tsx` | 84 | Render + collect new password + confirmation |
| `MfaVerifyForm.tsx` | 72 | Render + collect 6-digit MFA code |
| `AuthGate.tsx` | 485 | Auth state machine + transport wiring only (down from 622) |

Each form:
- Receives a typed `Props` interface (Interface Segregation)
- Renders only its own markup
- Calls injected `onSubmit` / `onBack` / `onForgot` callbacks
- Owns zero `useState` for cross-cutting concerns

**SOLID mapping:**
- **SRP:** Each component does one thing — render one form.
- **OCP:** Add a new auth view (SSO, magic link, passkey) by adding a new file, not editing `AuthGate.tsx`.
- **LSP:** Every form follows the same prop shape (`onSubmit`, `error`, `submitting`, …), so `AuthGate` can switch between them safely.
- **ISP:** Each form imports only the props it needs from the union.

### Layer 3: LoginForm exposes the "Forgot Password" link (Open/Closed)

`LoginForm.tsx` now renders two secondary actions below the primary submit:

```tsx
<AuthSecondaryAction
  label="نسيت كلمة المرور؟"
  onClick={onForgotPassword}
/>

<AuthSecondaryAction
  label="لديك دعوة؟ إنشاء حساب جديد"
  onClick={onCreateAccount}
/>
```

`AuthGate` wires these to `setAuthState("forgot")` and `setAuthState("register")`, reusing the existing handler functions that were already implemented but unreachable from the UI.

**SOLID mapping:**
- **OCP:** The link is added by composition (`<AuthSecondaryAction />`), not by editing the form's internal logic.

### Layer 4: Production-safe API URL fallback

**Modified file:** `frontend/src/lib/api.ts`

`resolveApiBaseUrl()` now:
- Uses `NEXT_PUBLIC_API_BASE_URL` if set
- For production builds on a public origin, falls back to `${protocol}//${host}/api` (same-origin)
- Still uses `http://127.0.0.1:8000` for local development
- Logs a console warning when the fallback is used

This means even if Railway loses the env var, the production frontend still talks to a same-origin backend (which Railway routes automatically to the BOB-2 service via `railway.toml`).

---

## 🧪 Verification

### Static analysis
- All new files pass `tsc --noEmit` (verified locally before commit)
- No new `any` types introduced
- All exported functions have explicit return types

### Functional checks (to run after deploy)
1. **Forgot password flow:**
   ```
   1. Open https://app.athmar-aisolution.net/
   2. Click "نسيت كلمة المرور؟"
   3. Enter email → "إرسال رابط إعادة التعيين"
   4. Backend responds with confirmation message
   ```

2. **No "Failed to fetch":**
   ```
   1. Set NEXT_PUBLIC_API_BASE_URL=https://api.athmar-aisolution.net on Railway
   2. Redeploy BOB FRONT END service
   3. Login attempt now reaches the backend (HTTP 200 or 401, not network error)
   ```

3. **Token refresh on 401:**
   ```
   1. Login with valid credentials
   2. Wait > access_token TTL (15 minutes default)
   3. Make any API call
   4. Expect: transparent refresh, no user-visible error
   ```

---

## 📦 Files Changed

```
BOB-2/frontend/src/lib/api.ts                              (modified, +33 lines)
BOB-2/frontend/src/lib/http-client.ts                       (new, 277 lines)
BOB-2/frontend/src/components/auth/AuthCard.tsx            (new, 133 lines)
BOB-2/frontend/src/components/auth/AuthGate.tsx            (modified, refactored, -137 net)
BOB-2/frontend/src/components/auth/LoginForm.tsx           (new, 96 lines)
BOB-2/frontend/src/components/auth/MfaVerifyForm.tsx       (new, 72 lines)
BOB-2/frontend/src/components/auth/PasswordResetRequestForm.tsx (new, 71 lines)
BOB-2/frontend/src/components/auth/PasswordResetConfirmForm.tsx (new, 84 lines)
```

**Total:** 7 files (5 new, 2 modified), 691 net new lines, 137 lines removed from `AuthGate`.

---

## 🚀 Deployment

After merging this branch:

1. **Railway → BOB FRONT END → Variables:**
   ```
   NEXT_PUBLIC_API_BASE_URL = https://api.athmar-aisolution.net
   ```

2. **Railway → BOB-2 → Variables:** (unchanged, already covered in `RAILWAY_ENV_UPDATE_GUIDE.md`)
   ```
   FRONTEND_ORIGIN = https://athmar-aisolution.net,https://app.athmar-aisolution.net
   CORS_ORIGINS = https://athmar-aisolution.net,https://app.athmar-aisolution.net
   TRUSTED_HOSTS = athmar-aisolution.net,app.athmar-aisolution.net,api.athmar-aisolution.net
   ```

3. **Trigger redeploy** (Railway does this automatically when env vars change)

4. **Verify:**
   - `https://app.athmar-aisolution.net/` shows the LoginForm with **نسيت كلمة المرور؟** link visible
   - Clicking the link routes to `/api/v1/auth/password-reset/request` (no "Failed to fetch")
   - Backend returns 200 with a message about sending the reset email

---

*Last updated: August 2026*
