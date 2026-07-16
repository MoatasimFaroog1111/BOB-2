# SaaS, Security and Support Schedule Template

> Commercial and legal template requiring completion and authorized review.

## Order details

| Field | Agreed value |
|---|---|
| Customer legal entity | [ ] |
| Provider legal entity | [ ] |
| Service / modules | [ ] |
| Hosting region | [ ] |
| Production start | [ ] |
| Initial term / renewal | [ ] |
| Users / tenants / usage limits | [ ] |
| Fees and taxes | [ ] |
| Implementation services | [ ] |
| Customer success owner | [ ] |

## Service scope

GuardianAI/BOB-2 provides configured accounting assistance, document processing, controlled ERP integration, reconciliation support and audit evidence. Unless expressly listed in the order form, it is not:

- a replacement for the customer's ERP/general ledger;
- an independent statutory auditor, tax adviser or legal adviser;
- a ZATCA-certified e-invoicing solution;
- authorized to post entries without customer-approved permissions and workflows;
- a guarantee that source documents or customer instructions are correct.

The customer remains responsible for source documents, chart of accounts, tax treatment, period controls, approval decisions, statutory filings and final financial statements.

## Availability target

- Monthly availability target: [99.5% / agreed value]
- Measurement point: HTTPS `/health` and dependency-aware `/ready`
- Exclusions: agreed maintenance, customer systems, unsupported integrations, force majeure, suspension for security/non-payment, and events outside Provider control
- Service-credit formula and cap: [complete]
- Credits are the remedy for missed availability only if legally and commercially approved in the main agreement.

## Support priorities

| Priority | Example | Initial response target | Update target | Target restoration/workaround |
|---|---|---:|---:|---:|
| P1 Critical | Production unavailable, confirmed cross-tenant exposure, material data corruption | [30 min] | [60 min] | [4 hours] |
| P2 High | Major workflow unavailable with no reasonable workaround | [2 hours] | [4 hours] | [1 business day] |
| P3 Normal | Degraded/non-critical feature or integration issue | [1 business day] | [2 business days] | Best efforts / planned release |
| P4 Request | Question, enhancement or configuration assistance | [2 business days] | As agreed | Roadmap / services quote |

Support hours, time zone, channels and emergency contacts: [complete].

## Security commitments

Provider will maintain:

- tenant-scoped authorization and regression tests;
- MFA capability and server-side session revocation;
- TLS for public traffic;
- PostgreSQL for production data and Redis for shared authentication limits;
- encrypted secret storage using an approved external vault or AES-256-GCM key kept outside the database;
- persistent storage, backup and tested restoration;
- dependency locking, vulnerability auditing and reviewed releases;
- append-only/tamper-evident audit controls within the documented trust boundary;
- incident response, logging and restricted administrative access.

Security commitments do not extend to customer-managed credentials, endpoints, ERP configuration, user decisions or integrations outside Provider control.

## Recovery objectives

- Backup frequency: [complete]
- Backup retention: [complete]
- Recovery point objective (RPO): [complete]
- Recovery time objective (RTO): [complete]
- Restore test frequency: at least [quarterly] and before material platform migration
- Customer export format and termination window: [complete]

Targets are commitments only after operational monitoring, backup schedules and staffing are activated and evidenced.

## Change management

Material production releases require green automated release gates, migration review, rollback plan and release record. Breaking API/integration changes require [notice period]. Emergency security changes may be deployed promptly with subsequent notice.

## Incident communication

Provider will use the contacts below for confirmed material incidents. Notices will state known scope, containment, likely customer impact, required customer actions and next update. Initial information may change as investigation proceeds.

| Role | Name | Email | Telephone |
|---|---|---|---|
| Customer incident owner | | | |
| Customer finance owner | | | |
| Provider incident commander | | | |
| Provider privacy contact | | | |

## Acceptance and human controls

Before live financial posting, the parties must complete and sign the Accounting UAT pack. Automated CI success does not approve accounting treatment. High-risk posting, user-role changes, secret rotation and production purge/offboarding require authorized human action and audit evidence.

## Signatures

Customer authorized signatory: ____________________ Date: __________  
Provider authorized signatory: ____________________ Date: __________  
Legal approval reference: ____________________
