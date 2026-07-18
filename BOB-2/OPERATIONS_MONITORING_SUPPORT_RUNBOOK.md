# Operations, Monitoring and Support Runbook

## Operational status rule

Monitoring is **ACTIVE** only after all of the following evidence exists:

- the production backend URL is configured in the monitoring system;
- `/health` and `/ready` are probed from outside Railway;
- at least two authorized people receive and acknowledge test alerts;
- PostgreSQL backup schedules and retention are configured;
- one production-like restore drill is recorded;
- incident and customer contacts are completed;
- the support rota has named coverage.

A committed workflow or runbook alone is `READY TO ACTIVATE`, not `ACTIVE`.

## Endpoints

- `/health`: process liveness only. It intentionally does not depend on the database.
- `/ready`: dependency readiness. Returns HTTP 503 if PostgreSQL, Redis or persistent storage is unavailable. It exposes component booleans only, not credentials or exception text.

Railway should continue to use `/health` for restart/liveness decisions. External monitoring and release verification should monitor both endpoints; a `/ready` failure triggers investigation without causing an automatic restart loop.

## Minimum monitoring

| Signal | Condition | Severity | Initial action |
|---|---|---|---|
| `/health` | Non-200 for 2 consecutive probes | P1 | Confirm Railway deployment/container state and recent release |
| `/ready` | 503 for 2 consecutive probes | P1/P2 | Identify DB, Redis or storage dependency; preserve evidence |
| Authentication | Spike in 429/503 or refresh replay | P2 / security | Review rate limiter, Redis and session security events |
| Audit chain | Integrity check fails | P1 security | Freeze affected financial posting; preserve DB and logs |
| Tenant access | Any confirmed cross-tenant exposure | P1 security/privacy | Isolate service, activate breach procedure, legal/privacy assessment |
| Database | Connection or migration failure | P1 | Stop release, validate credentials/network/migration head |
| Storage | Write failure or volume missing | P1 | Stop uploads/posting, verify Railway volume mount |
| Backup | Scheduled backup missing/invalid | P1 | Run protected backup, diagnose schedule, do not delete prior good backup |
| Malware scan | Scanner unavailable while required | P1 | Fail closed for uploads; restore scanner service |
| Odoo posting | Duplicate or ambiguous result | P1 finance | Stop retries, reconcile Odoo and audit event manually |
| Dependency scan | Critical/high actionable finding | Release blocker | Patch or formally document non-applicability before release |

## Incident roles

| Role | Primary | Backup | Contact |
|---|---|---|---|
| Incident commander | [name] | [name] | [phone/email] |
| Technical lead | [name] | [name] | [phone/email] |
| Finance control owner | [name] | [name] | [phone/email] |
| Privacy/legal contact | [name] | [name] | [phone/email] |
| Customer communications | [name] | [name] | [phone/email] |

## Incident lifecycle

1. **Detect and acknowledge:** record time, signal, reporter, release SHA and affected tenants.
2. **Classify:** availability, security/privacy, financial integrity, integration or support.
3. **Contain:** restrict access, disable affected integration/feature or roll back. Never delete evidence.
4. **Preserve:** logs, audit-chain head, relevant DB snapshot, deployment metadata and user reports.
5. **Assess:** scope, data/transactions affected, legal notification requirements and customer impact.
6. **Communicate:** use approved contacts; state known facts, containment and next update time.
7. **Recover:** restore from known-good state, reconcile accounting results and verify `/health`, `/ready`, audit chain and tenant isolation.
8. **Close:** customer confirmation where applicable, root-cause analysis, corrective actions and evidence retention.

## Backup and recovery

Production settings to complete:

- PostgreSQL backup mechanism: [Railway backup / external encrypted backup]
- Frequency: [ ]
- Retention: [ ]
- Storage location and encryption owner: [ ]
- RPO: [ ]
- RTO: [ ]
- Restore drill frequency: [quarterly or approved interval]
- Last successful restore evidence: [link/date]

The CI PostgreSQL release gate proves that the schema can be dumped and restored in an isolated environment. It does not configure production backups.

## Release procedure

1. Identify exact commit and approved PR.
2. Require all automated checks green, including PostgreSQL restore, Railway image, tenant isolation and security scans.
3. Review migrations and backup current production database.
4. Confirm Railway production variables, Redis, PostgreSQL and volume mount.
5. Deploy; verify `/health` then `/ready`.
6. Run a read-only tenant smoke test and audit-chain check.
7. Monitor error rate and posting results during the observation window.
8. Record release owner, time, evidence and rollback decision.

## Rollback

- Application rollback must use an identified prior image/commit.
- Database downgrade is not automatic. Prefer a compatible forward fix or restore only after impact analysis and authorized approval.
- Never restore a database without reconciling transactions posted to Odoo or other external systems after the backup point.
- Rotate secrets if an incident involved credential exposure.

## Support intake

Every ticket records customer, tenant, affected user, time zone, release, environment, expected/actual result, financial impact, screenshots without secrets, source-document hash and urgency. Support personnel must not request passwords, API keys, TOTP secrets or unrestricted production exports.

## Activation record

- Production backend URL configured: ☐
- Test `/health` alert received: ☐
- Test `/ready` alert received: ☐
- Primary and backup acknowledged alerts: ☐
- Production backup scheduled: ☐
- Restore evidence retained: ☐
- Incident contacts completed: ☐
- Support rota approved: ☐

Activated by: ____________________  
Date/time: ____________________  
Evidence links: ____________________
