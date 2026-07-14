# GuardianAI security deployment runbook

This checklist is mandatory before exposing the application to the Internet or using real accounting data.

## 1. Contain and rotate existing credentials

1. Stop public access to the backend and PostgreSQL.
2. Remove any firewall/security-group rule that permits inbound TCP/5432 from outside the private application network.
3. Rotate the PostgreSQL password and update the URL-encoded value in `DATABASE_URL`.
4. Rotate `SECRET_KEY`. This invalidates all JWTs issued with the previous key.
5. Apply the latest Alembic migrations. Migration `7f1a2b3c4d5e` disables the previously seeded `owner@guardian.local` account.
6. Do not reactivate that account until a new, unique password has been set through a controlled administrative procedure.
7. Rotate any ERP, email, Telegram, or LLM credentials that may have been stored in or exposed through a prior deployment.

Changing source code does not rotate a password that already exists in a live database. The operational rotations above are required.

## 2. Required production variables

Set all of the following through the deployment platform's secret manager, not in Git:

- `APP_ENV=production`
- `DATABASE_URL`
- `POSTGRES_PASSWORD`
- `REDIS_PASSWORD`
- `REDIS_URL`
- `SECRET_KEY`
- `FRONTEND_ORIGIN` using `https://`
- `NEXT_PUBLIC_API_BASE_URL` using `https://`
- `TRUSTED_HOSTS`
- `TRUSTED_PROXY_IPS` when a reverse proxy is used
- `REQUIRE_HTTPS=true`
- `CLAMAV_HOST`
- `REQUIRE_MALWARE_SCAN=true`
- `TELEGRAM_BOT_ENABLED=false`
- `TELEGRAM_BOT_PRODUCTION_READY=false`
<<<<<<< HEAD
=======
- `TELEGRAM_ALLOW_GROUP_CHATS=false`
>>>>>>> origin/main

The backend deliberately refuses to start when mandatory production controls are missing. Telegram is separately fail-closed: even a legacy endpoint cannot start the bot unless the centralized runtime policy allows it.

## 3. Network controls

- Publish only the HTTPS reverse proxy or application gateway.
- Keep PostgreSQL, Redis, and ClamAV on the private Docker/application network.
- Permit the backend to connect to those services; deny direct Internet access to them.
- Configure the reverse proxy to overwrite, not append blindly to, `X-Forwarded-For` and `X-Real-IP`.
- Put only the proxy's actual IP/CIDR in `TRUSTED_PROXY_IPS`.
- Restrict administrative access by VPN or an identity-aware gateway where possible.

## 4. TLS and host validation

- Terminate TLS at a trusted reverse proxy or managed application gateway.
- Redirect HTTP to HTTPS at the edge and block direct public access to the backend HTTP port.
- Set `TRUSTED_HOSTS` to the exact application/API hostnames. Do not use `*` in production.
- Keep HSTS enabled only after HTTPS is confirmed on all intended subdomains.

## 5. Database and account bootstrap

Production no longer creates an owner automatically. Provision the first administrator using a controlled one-time procedure that:

- creates a unique account tied to the correct organization;
- uses a password of at least 12 characters from a password manager;
- records the action in the audit log;
- removes or disables the bootstrap mechanism immediately afterward.

Never restore the published password `Owner@Seed#2026!`.

## 6. Validation before release

Run and require success for:

```bash
cd BOB-2/backend
python -m compileall -q app tests
pytest -q
pip-audit -r requirements.lock --strict

cd ../frontend
npm ci --ignore-scripts
npm audit --audit-level=high
npm run build
```

Also perform dynamic validation in an isolated staging environment:

- verify PostgreSQL/Redis/ClamAV are not externally reachable;
- test login throttling across multiple backend workers;
- verify refresh-token rotation and reuse detection;
- verify logout immediately rejects the old access token;
- upload malformed, macro-enabled, oversized, and malware test files;
- verify tenant A cannot read tenant B journals/documents;
- test reverse-proxy Host and forwarded-IP handling;
- run an authenticated DAST scan and review application/container logs.

## 7. Monitoring and incident response

Alert on:

- repeated login lockouts or refresh-token reuse;
- unexpected owner/admin creation or reactivation;
- malware detections and failed scanner connections;
- database authentication failures;
- changes to production secrets or trusted hosts/proxies;
- unusual journal reads/exports and failed authorization checks;
- attempts to start Telegram while the policy blocks it;
<<<<<<< HEAD
- Telegram emergency-disable events and cleared pending operations.
=======
- Telegram emergency-disable events and cleared pending operations;
- Telegram access denials, inactive identity bindings, tenant mismatches, and permission failures.
>>>>>>> origin/main

Retain audit and security logs in append-only or centrally controlled storage with access restricted to authorized administrators and auditors.

## 8. Telegram production shutdown control

Until every later Telegram hardening stage is completed, production must keep:

```env
TELEGRAM_BOT_ENABLED=false
TELEGRAM_BOT_PRODUCTION_READY=false
<<<<<<< HEAD
=======
TELEGRAM_ALLOW_GROUP_CHATS=false
>>>>>>> origin/main
```

The central runtime guard patches the legacy start and stop functions, so the historical `/api/v1/erp/telegram-config` endpoint cannot bypass this policy. A blocked start also synchronizes the legacy UI state to inactive, stops polling, and clears in-memory pending entries.

Authorized administrators can review secret-free runtime status at:

- UI: `/admin/telegram`
- API: `GET /api/v1/telegram/runtime-status`

The emergency control is:

- UI button on `/admin/telegram`
- API: `POST /api/v1/telegram/emergency-disable`

The emergency action requires `manage_settings`, immediately stops polling, clears pending entries, and creates a centralized audit record. No application endpoint is provided to reverse an emergency stop in production.
<<<<<<< HEAD
=======

## 9. Telegram identity allowlist

Apply migration `4c9d7e2a1b60` before configuring identities. Each allowlist row binds all of the following values:

- exact Telegram user ID;
- exact Telegram chat ID;
- one `organization_id`;
- one active system user in that organization;
- the administrator who created the binding;
- optional per-row group-chat permission.

Manage bindings only through the authenticated administration page `/admin/telegram` or the `manage_settings` endpoints under `/api/v1/telegram/authorizations`. Do not insert rows manually except during a controlled recovery procedure.

Security behavior:

- every Telegram message and callback verifies `from.id`, `chat.id`, and chat type;
- permissions are read from the linked system user's current database role on every operation;
- inactive bindings, users, and organizations fail closed;
- channels are rejected;
- groups and supergroups require both `TELEGRAM_ALLOW_GROUP_CHATS=true` and `allow_group_chats=true` on the exact row;
- pending work is keyed by both chat ID and Telegram user ID, so another group member cannot approve it;
- deactivating a binding clears that actor's pending work;
- every grant and denial is written to the central audit table without tokens or passwords.

The legacy posting implementation still supports only organization 1 and is explicitly blocked for other organizations. Do not set `TELEGRAM_BOT_PRODUCTION_READY=true` until the independent tenant-aware posting and approval service is completed.
>>>>>>> origin/main
