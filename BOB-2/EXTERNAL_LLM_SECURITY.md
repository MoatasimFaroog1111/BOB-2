# External LLM disclosure security

This control set separates technical access to an external model from organizational authorization to disclose data.

## Default production posture

Both model paths remain disabled in the production Compose profile:

```env
LOCAL_LLM_ENABLED=false
EXTERNAL_LLM_ENABLED=false
```

The Telegram bot also remains disabled. Completing this stage does not authorize enabling Telegram or moving application secrets into ordinary environment variables as a final production design.

## No automatic external fallback

Legacy callers use `backend/app/services/llm_service.py`. That module is local-only:

- it returns no model output when `LOCAL_LLM_ENABLED=false`;
- it only accepts a loopback Ollama URL;
- every resolved address must be loopback;
- the socket is pinned to the validated loopback address;
- responses are size and timeout bounded;
- it contains no DeepSeek/OpenAI/Internet fallback.

Therefore bank reconciliation, natural-language intent classification, and older ERP helpers cannot silently send data externally merely because an API key exists.

## Two independent external gates

An external request requires both:

1. a global deployment switch, exact provider/model/host allowlists, and a technical API key; and
2. an active tenant policy stored in `external_llm_policies`.

A key is a credential only. It is never considered consent.

The tenant policy is scoped by `organization_id` and records:

- approved provider and model;
- approved purposes;
- whether redacted document text may be included;
- whether financial values may be included;
- maximum redacted text length;
- DPA version and reference;
- agreed data-residency region;
- contractual retention mode;
- accepting system user and timestamp;
- revoking system user and timestamp;
- policy version and review time.

## DPA and legal review

The application enforces that a tenant administrator records the exact required DPA version, a non-empty reference, region, approved retention mode, accepting user, and acceptance time. Material provider/model/DPA changes require a new explicit acceptance.

The software cannot prove that the referenced contract is genuine, sufficient, signed by the correct legal parties, or compliant with every jurisdiction. A qualified legal/privacy reviewer must validate the real agreement and configure the reference accurately before any production enablement.

## Approved purposes

The gateway recognizes only:

```text
accounting_reasoning
natural_language_intent
bank_reconciliation_matching
```

A tenant must select each purpose explicitly. Unknown or unapproved purposes fail closed.

The current Stage 6 integration uses the gateway for `accounting_reasoning`. Legacy natural-language and reconciliation callers remain local-only until they are explicitly migrated with authenticated context and tenant approval.

## Authenticated context

Every external request must carry:

- current organization ID;
- current system user ID;
- approved purpose;
- source type;
- request ID.

The gateway verifies that the organization is active and that the user is active and belongs to that organization. Client-supplied organization IDs cannot override the authenticated tenant.

## Data minimization and redaction

The external payload is rebuilt from a structured rule-based result. The raw document is not embedded in the structured payload.

By default:

- raw document text is omitted;
- party, partner, supplier, vendor, customer, employee, person, contact, and address fields are removed;
- email, phone, IBAN, account, VAT, tax, national-ID, invoice, and reference fields are removed;
- password, token, secret, authorization, API-key, and private-key fields are removed;
- amount, subtotal, total, balance, debit, credit, price, cost, salary, and wage fields are removed.

If the tenant explicitly permits redacted document text, the text is capped by both the tenant limit and the global limit. The redactor removes:

- labeled party/name/address lines in English and Arabic;
- emails;
- IBANs;
- Saudi VAT numbers;
- Saudi identity patterns;
- phone-like identifiers;
- accounting references such as INV/PO/JE/BILL/PV/RV/SO/RFQ;
- long numeric identifiers;
- currency amounts, grouped amounts, and two-decimal values when financial disclosure is disabled.

Automated redaction reduces exposure but is not a guarantee that every possible natural-language identifier can be recognized. Production policy should keep raw document text disabled unless a documented privacy review approves the residual risk.

## Pre-disclosure audit gate

Before the transport is called, the application commits an `external_llm_disclosure_started` audit event. If that commit fails, no provider request is made.

Separate append-style events record:

```text
external_llm_disclosure_blocked
external_llm_disclosure_started
external_llm_disclosure_succeeded
external_llm_disclosure_failed
```

Audit details contain only non-content metadata such as:

- request ID;
- organization/user IDs through the audit record;
- purpose and source type;
- provider and model;
- policy ID/version and DPA version;
- canonical SHA-256 payload hash;
- sanitized payload and request byte counts;
- redaction-category counts;
- included redacted-text length;
- output character count;
- internal status/reason code.

They do not contain the system prompt, user prompt, raw document text, sanitized document text, API key, authorization header, or provider response.

## External network transport

The gateway accepts only an exact configured HTTPS host on port 443 and a `/chat/completions` endpoint. It rejects:

- HTTP;
- alternate/unapproved hosts;
- URL credentials;
- query strings and fragments;
- alternate ports;
- encoded, duplicate-separator, or traversal paths;
- proxy tunnels;
- loopback, private, link-local, multicast, reserved, unspecified, metadata, and non-global DNS answers.

Every DNS result is validated. The TLS socket is pinned to a validated public address while certificate verification and SNI use the original hostname. The client does not follow redirects. Request and response sizes and timeouts are bounded.

## Administration API and UI

Backend endpoints:

```text
GET  /api/v1/llm/policy
PUT  /api/v1/llm/policy
GET  /api/v1/llm/disclosures
```

Policy reads and writes require `manage_settings`. Disclosure history requires `view_audit_logs`. All queries are tenant-scoped.

The UI is available at:

```text
/admin/llm
```

It shows only whether a technical key is configured. It never displays the key or a prefix of it. It also displays the policy, required DPA version, effective fail-closed state, and safe disclosure metadata.

## Deployment procedure

Before considering external processing:

1. Keep `EXTERNAL_LLM_ENABLED=false` during review.
2. Complete privacy, security, procurement, and legal review of the real provider contract.
3. Confirm no-training/retention terms and data-residency commitments.
4. Set exact provider, model, and host allowlists.
5. Store the provider credential in the approved secret-management system; do not treat `.env` as the final secret-store design.
6. Apply migration `7a4c9e2d1f60`.
7. Have an authorized tenant administrator record the real DPA reference and approve only necessary purposes.
8. Keep redacted document text and financial values disabled unless separately justified.
9. Enable the global switch through a reviewed deployment change.
10. Run a non-sensitive test and verify blocked/started/succeeded/failed audit events.
11. Review logs to confirm prompts, documents, keys, and provider bodies are absent.
12. Maintain an emergency process that sets `EXTERNAL_LLM_ENABLED=false` and disables tenant policies.

## CI requirements

CI must fail if:

- DeepSeek or another external fallback returns to `llm_service.py`;
- the accounting reasoner directly uses an HTTP library instead of the gateway;
- the global kill switch, tenant policy, DPA, provider/model/purpose checks disappear;
- pre-send audit persistence disappears;
- party/identifier/financial redaction disappears;
- external endpoint validation, DNS pinning, TLS hostname verification, or size limits disappear;
- Compose enables either local or external LLM execution;
- policy responses or disclosure logs expose API keys, prompts, raw text, or provider responses.

The dedicated regression suite is:

```text
backend/tests/test_external_llm_security.py
```
