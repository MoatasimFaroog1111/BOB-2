# Architecture Decision Record — Multi-GTM Support

> Status: **Proposed** for the `feature/saas-readiness` branch
> Target commit base: `27f46d1`
> Author: Hermes (Chief Software Engineer, executive role delegated by repo owner)
> Reviewers: repo owner, future Acquire buyer

## Context

The `BOB-2` / `GuardianAI Accountant & Auditor Enterprise` codebase is, by
design, an **invite-only enterprise B2B platform**: it has no self-serve
signup, no Stripe billing, no pricing tiers, and no marketing site. The
current repository documentation describes it correctly as "Enterprise-grade
AI accounting, auditing, tax compliance, and ERP execution platform" with
"production-oriented security controls".

The repo owner is preparing the project for sale on Acquire.com and similar
marketplaces and asked for **three go-to-market (GTM) frames** to be
expressible from the same codebase so the same asset reaches three buyer
personas without forks:

1. **Frame A — Enterprise Takeover (single-buyer asset sale).**
   What Acquire.com itself defaults to: one buyer acquires the company,
   source code, customer relationships, and operational infrastructure.
   The buyer is operator-led, expects a 30/60/90-day handoff, and pays for
   the *existing* revenue stream plus platform.

2. **Frame B — Self-Serve SaaS (multi-tenant subscription).**
   What most listing pitches actually describe: end customers sign up
   themselves, pay via Stripe or Lemon Squeezy, manage their own tenants,
   with usage-based or tiered pricing. Requires a marketing site, billing
   integration, self-serve tenant onboarding, and a fundamentally different
   signup flow than the current invite-only path.

3. **Frame C — Hybrid Marketplace (operator-led + self-serve).**
   What AppSumo, Lemon Squeezy, and "lifetime deal" marketplaces reward:
   a self-serve acquisition channel combined with operator-led activation.
   Customers buy cheaply, the operator runs onboarding and first-value
   sessions, and the platform collects revenue across many small tenants.

The hard requirement is that **a single codebase can be configured,
deployed, and sold as any one of the three frames** without forking,
without a separate "SaaS edition" repository, and without weakening the
enterprise security posture that already exists.

## Goals

- One FastAPI backend, one Next.js frontend, one PostgreSQL schema.
- Configuration flag `DEPLOYMENT_FRAME` (default `enterprise`, values
  `enterprise`, `self_serve_saas`, `hybrid_marketplace`) controls which
  surface area is active. The same code path serves all three.
- All three frames pass the existing `pytest` security baseline with no
  regressions.
- No dependency on proprietary SaaS infrastructure (Stripe webhooks run
  even if Stripe is not configured; billing service degrades to a
  deterministic in-process ledger).
- The Acquire listing can quote the same engineering metrics for any
  frame because the underlying build is the same.

## Non-goals

- Building a fully-featured Stripe billing portal (we ship a focused,
  minimal billing surface — invoices, webhooks, plan switching).
- Replacing Odoo as the ERP target. The current scope stays Odoo-only;
  SAP/Oracle connectors remain explicitly out of scope.
- ZATCA certification or any regulated e-invoicing claim.
- Implementing the actual Acquire.com listing submission; that is an
  owner-driven step outside this codebase.

## Decisions

### D1. Configuration-driven frame switching

Introduce a single `DEPLOYMENT_FRAME` setting in `app/core/config.py`
validated against an explicit enum:

```python
class DeploymentFrame(str, Enum):
    ENTERPRISE = "enterprise"
    SELF_SERVE_SAAS = "self_serve_saas"
    HYBRID_MARKETPLACE = "hybrid_marketplace"
```

Each frame maps to a deterministic capability set:

| Capability                          | Enterprise | Self-Serve SaaS | Hybrid |
|-------------------------------------|:----------:|:---------------:|:------:|
| Invitation-only signup (current)    | ✅ default | disabled        | opt-in |
| Self-serve signup + email verify    | disabled   | ✅ default      | ✅ default |
| Stripe billing integration          | disabled   | ✅ default      | ✅ default |
| Lemon Squeezy / marketplace billing | disabled   | optional        | ✅ default |
| Marketing site (`/`, `/pricing`)    | hidden     | ✅ default      | ✅ default |
| Operator-led onboarding dashboard   | optional   | disabled        | ✅ default |
| Public demo environment             | disabled   | optional        | ✅ default |
| Per-tenant usage metering           | optional   | ✅ default      | ✅ default |
| Audit-chain export to S3            | optional   | ✅ default      | ✅ default |

The capabilities are exposed via `GET /api/v1/system/capabilities` so the
frontend can hide or render only the relevant surfaces without recompiling.

### D2. Backwards compatibility is non-negotiable

The current security baseline must remain intact:

- Production startup still requires Redis, PostgreSQL, a real secret store,
  ClamAV, ERP allowlist, and HTTPS regardless of `DEPLOYMENT_FRAME`.
- The `fail-closed` `_validate_startup_security` validator in `app/main.py`
  is updated only to add a single new check (frame-specific extra
  requirements), never to weaken existing ones.
- Existing invite-only signup (`POST /api/v1/auth/register` with invite
  token) continues to work unchanged in every frame. In `self_serve_saas`
  and `hybrid_marketplace`, a parallel `POST /api/v1/auth/signup` is added
  *without* modifying the existing invite path.

### D3. SOLID-driven module boundaries

Each frame's new code lives under a clearly named module that mirrors the
existing `app/` structure:

```
app/
  billing/             # Frame B/C — Stripe + Lemon Squeezy + ledger
    stripe_provider.py
    lemonsqueezy_provider.py
    in_memory_provider.py  # dev/test fallback when no provider configured
    service.py             # interface used by application code
    webhooks.py
  onboarding/          # Frame B/C — self-serve signup, email verify,
                       # tenant provisioning
    signup_service.py
    email_verifier.py
    tenant_provisioner.py
  capabilities/        # Frame switcher — single source of truth for
                       # which surface is active
    service.py
    router.py
  marketing/           # Frame B/C — public landing data
    pages.py           # pricing tiers, FAQ, comparison table
```

The frontend mirrors this with:

```
frontend/src/
  features/
    marketing/         # Frame B/C — pricing page, comparison page
    self-serve-signup/ # Frame B/C — public signup form
    onboarding/        # Frame B/C — first-run wizard after signup
    billing/           # Frame B/C — Stripe Customer Portal entry
```

The SOLID principles that drive this layout:

- **S** — each module has one reason to change (billing, onboarding,
  capabilities, marketing).
- **O** — adding a new frame or a new billing provider does not require
  editing existing modules.
- **L** — every billing provider implements the same `BillingProvider`
  interface; swapping one for another is safe.
- **I** — narrow interfaces (`BillingProvider.charge`, `BillingProvider.refund`)
  instead of fat ones.
- **D** — application code depends on the `BillingProvider` abstraction,
  never on a concrete provider. The capability service is the high-level
  abstraction the frontend talks to.

### D4. Three Acquire-ready sale documents

`sale/` will gain:

- `ACQUIRE_LISTING_ENTERPRISE_TAKEOVER.md` — Frame A pitch.
- `ACQUIRE_LISTING_SELF_SERVE_SAAS.md` — Frame B pitch.
- `ACQUIRE_LISTING_HYBRID_MARKETPLACE.md` — Frame C pitch.
- `PRICING_TIERS.md` — the actual price points and included limits per
  frame, with placeholders (`TBD`) for revenue, churn, and customer
  metrics that only the owner can supply.

Each listing is self-consistent, references the same verified evidence
from `VERIFICATION_REPORT_2026-08-04.md`, and ends with the same set of
`TBD` owner-supplied fields.

### D5. Single test harness, three test matrices

The existing `pytest` suite is the contract. We add new tests under:

```
backend/tests/test_billing_provider_in_memory.py
backend/tests/test_self_serve_signup.py
backend/tests/test_capabilities_router.py
backend/tests/test_deployment_frame_config.py
backend/tests/test_tenant_provisioning.py
```

Each new test runs in all three frames. Frame-specific assertions
(parametrize on `DEPLOYMENT_FRAME`) verify that capabilities light up or
stay hidden as expected. The CI pipeline is extended with:

```
backend-capabilities-test:
  strategy:
    matrix:
      frame: [enterprise, self_serve_saas, hybrid_marketplace]
```

### D6. Zero hard dependency on third-party SaaS

If the operator configures no billing provider, the `in_memory_provider`
runs and records ledger entries in the application database. This means
the codebase is **fully runnable** for any frame in a local dev
environment with only PostgreSQL, Redis, and an SMTP catch-all. Stripe
is an *optional* dependency on top.

### D7. Operator credentials vault (Frame A focus)

For Enterprise Takeover, we ship an *Operator Credentials Kit* — a
script-driven handoff that:

- Generates an audit-safe ownership transfer document.
- Rotates all tenant secret-store entries and writes the new encryption
  key to a sealed envelope.
- Re-signs every JWT signing key.
- Produces a `BUYER_HANDOFF.md` with the exact DNS, Railway, GitHub,
  Stripe, and SMTP settings the new owner must configure.

For Self-Serve SaaS and Hybrid, the same kit is reused as the *Data
Room Export* without the rotation step (since there is no single buyer).

## Concrete file-level impact

### Backend (new files)

| Path                                              | Purpose                                            |
|---------------------------------------------------|----------------------------------------------------|
| `app/core/deployment_frame.py`                    | `DeploymentFrame` enum + validators.               |
| `app/billing/__init__.py`                         | Module marker.                                     |
| `app/billing/service.py`                          | `BillingService` facade.                           |
| `app/billing/types.py`                            | `BillingProvider` protocol + dataclasses.          |
| `app/billing/in_memory_provider.py`               | Deterministic ledger fallback (always available).  |
| `app/billing/stripe_provider.py`                  | Stripe implementation behind the protocol.         |
| `app/billing/lemonsqueezy_provider.py`            | Lemon Squeezy implementation behind the protocol.  |
| `app/billing/webhooks.py`                         | Webhook entrypoint with signature verification.    |
| `app/onboarding/__init__.py`                      | Module marker.                                     |
| `app/onboarding/signup_service.py`                | Self-serve signup business rules.                  |
| `app/onboarding/email_verifier.py`                | Token +24h, single-use, hashed-at-rest.           |
| `app/onboarding/tenant_provisioner.py`            | Atomic org + owner + first role.                   |
| `app/capabilities/__init__.py`                    | Module marker.                                     |
| `app/capabilities/service.py`                     | `CapabilitiesService` reads config + returns map.  |
| `app/capabilities/router.py`                      | `GET /api/v1/system/capabilities`.                 |
| `app/api/v1/signup.py`                            | `POST /api/v1/auth/signup`, `POST /verify-email`.  |
| `app/api/v1/billing.py`                           | Billing endpoints (plans, checkout, portal).       |
| `app/services/deployment_frame_check.py`          | Frame-specific fail-closed rules.                  |
| `app/security/dependencies.py`                    | Add `enforce_capability(name)` dependency.         |

### Backend (modified files)

| Path                                              | Change                                              |
|---------------------------------------------------|-----------------------------------------------------|
| `app/core/config.py`                              | Add `DEPLOYMENT_FRAME`, billing/onboarding fields.  |
| `app/main.py`                                     | Call new capability check + capability router.      |
| `app/api/v1/router.py`                            | Include new routers under `/system`, `/auth`, `/billing`. |
| `app/db/seed.py`                                  | Idempotent seeding per frame.                       |
| `backend/requirements.txt`                        | Bump `cryptography` to `>=50.0.0`.                  |
| `backend/requirements.lock`                       | Regenerated via `pip-compile`.                      |
| `.env.example`                                    | Document new env vars per frame.                    |

### Frontend (new files)

| Path                                                       | Purpose                              |
|------------------------------------------------------------|--------------------------------------|
| `frontend/src/app/(marketing)/page.tsx`                    | Public landing page (Frame B/C).     |
| `frontend/src/app/(marketing)/pricing/page.tsx`            | Pricing tiers.                       |
| `frontend/src/app/(marketing)/compare/page.tsx`            | Comparison table (Frames A/B/C).     |
| `frontend/src/app/signup/page.tsx`                         | Self-serve signup (Frame B/C).       |
| `frontend/src/app/verify-email/page.tsx`                   | Email verification landing.          |
| `frontend/src/features/billing/PlansPanel.tsx`             | Pricing comparison component.        |
| `frontend/src/features/billing/CheckoutButton.tsx`         | Stripe Checkout launcher.            |
| `frontend/src/features/onboarding/FirstRunWizard.tsx`      | Tenant-first-run wizard.             |
| `frontend/src/features/capabilities/useCapabilities.ts`    | React hook over `/api/v1/system/capabilities`. |

### Frontend (modified files)

| Path                                       | Change                                              |
|--------------------------------------------|-----------------------------------------------------|
| `frontend/src/app/layout.tsx`              | Render marketing layout for unauth, app layout for auth. |
| `frontend/src/proxy.ts`                    | Add marketing routes to CSP.                       |
| `frontend/src/components/auth/AuthGate.tsx`| Read capabilities before gating signup.             |

### Sale documents (new files)

| Path                                                       | Purpose                              |
|------------------------------------------------------------|--------------------------------------|
| `sale/ACQUIRE_LISTING_ENTERPRISE_TAKEOVER.md`             | Frame A listing draft.               |
| `sale/ACQUIRE_LISTING_SELF_SERVE_SAAS.md`                 | Frame B listing draft.               |
| `sale/ACQUIRE_LISTING_HYBRID_MARKETPLACE.md`              | Frame C listing draft.               |
| `sale/PRICING_TIERS.md`                                    | Unified tier table across frames.    |
| `sale/BUYER_HANDOFF_KIT.md`                                | Frame A handoff script.              |
| `sale/DATA_ROOM_EXPORT.md`                                 | Frame B/C data-room export script.   |

### CI

| Path                                                       | Purpose                              |
|------------------------------------------------------------|--------------------------------------|
| `.github/workflows/frame-matrix.yml`                       | Matrix build/test across all three frames. |
| `.github/workflows/billing-webhook-replay.yml`             | Replay-mode billing integration tests.    |

## Verification plan (post-implementation)

1. `pytest tests/ -q --tb=short` with `DEPLOYMENT_FRAME` matrix:
   enterprise / self_serve_saas / hybrid_marketplace. Target: 100% pass
   for the existing security baseline + new frame tests.
2. `pip-audit -r requirements.lock --strict` — must report 0 findings
   after the `cryptography` bump.
3. `npm run lint` and `npm run build` in `frontend/` — 0 errors.
4. Live HTTP smoke (`/health`, `/ready`, `/openapi.json`,
   `/api/v1/system/capabilities`) in each frame.
5. End-to-end browser smoke: public marketing page → pricing →
   self-serve signup → email verify → dashboard in frames B and C.
   Frame A: marketing page hidden, signup disabled, but dashboard still
   reachable behind owner invite.
6. Re-run the documented `VERIFICATION_REPORT` procedure and append a
   `VERIFICATION_REPORT_MULTI_GTM.md` that shows the matrix results.

## Risks and mitigations

- **Risk:** Scope creep into a full commercial SaaS product.
  **Mitigation:** D6 — the `in_memory_provider` makes the build
  runnable without Stripe, so we ship a complete codebase even when
  no real billing account is connected. The Acquire listing is honest
  about which integrations are configured vs runnable in dev.

- **Risk:** Regressing the existing enterprise security posture.
  **Mitigation:** D2 + new fail-closed rule in
  `services/deployment_frame_check.py` that requires the same Redis /
  PostgreSQL / secret-store / ClamAV / ERP allowlist regardless of
  frame. CI matrix runs the existing security tests under each frame.

- **Risk:** Stripe / Lemon Squeezy API drift.
  **Mitigation:** D3 — narrow protocol means a provider swap is a
  single file. CI replay workflow exercises recorded webhooks against
  the in-process verifier.

- **Risk:** The repo owner is not ready to publish a SaaS-style listing
  without verified revenue.
  **Mitigation:** D4 — each listing ends with `TBD` placeholders that
  only the owner can fill. The listing copy is *drafted*, not
  *submitted*.

## Definition of done

- All seven milestones (`P0` through `P6`) committed to
  `feature/saas-readiness`.
- `PUSH` to `origin/feature/saas-readiness` succeeds with the
  supplied GitHub PAT.
- A pull request is opened against `main`.
- Railway redeploys the PR build and `GET /health` returns 200 on the
  live URL.
- `VERIFICATION_REPORT_MULTI_GTM.md` is generated and committed.

This ADR is the single source of truth for the multi-GTM work. All
subsequent implementation steps reference it.
