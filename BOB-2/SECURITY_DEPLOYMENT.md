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

The backend deliberately refuses to start when mandatory production controls are missing.

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
pip-audit -r requirements.txt --strict

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
- unusual journal reads/exports and failed authorization checks.

Retain audit and security logs in append-only or centrally controlled storage with access restricted to authorized administrators and auditors.
