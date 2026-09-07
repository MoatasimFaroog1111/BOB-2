# Issue #117 — GuardianAI Reconcile for Odoo UAT Evidence

**Scope:** first paid-pilot release gate for bank reconciliation  
**Data class:** synthetic, non-customer, SAR  
**Test period:** August 2026  
**Branch:** `uat/issue-117-pilot-gate`  
**Automated gate commit:** `076f2c7a0d0433c9c4e8d451334f63a1aa559693`  
**GitHub Actions run:** `34021020518` — `Issue 117 UAT gate`  
**Live tested commit:** `f498d229003dfed89094dff667dc566621aeb9d8`  
**Railway environment:** `staging-demo-buyer`  
**BOB-2-UAT deployment:** `fcb2ec7b-b40a-4b56-863e-3467686d1122`  
**Live UAT runner deployment:** `f795d055-593d-41c8-b6a4-911d30e295c8`  
**Status:** PASS — AUTOMATED + LIVE ISOLATED ODOO EVIDENCE COMPLETE

## 1. Scenario

The synthetic statement contains six transactions and the synthetic Odoo ledger contains six transactions. Expected and verified reconciliation contract:

- 5 matched transactions.
- 1 statement-only transaction: SAR 57.50 bank service fee.
- 1 ledger-only transaction: SAR 1,250.00 unpresented cheque.
- The bank-service-fee exception remains under human review and has a balanced proposed entry: Debit Bank Charges SAR 57.50 / Credit Bank SAR 57.50.
- The unpresented cheque remains visible and must not trigger automatic posting.

Source fixtures:

- `bank_statement.csv`
- `odoo_ledger.csv`
- `expected_results.json`

## 2. Automated acceptance evidence

The dedicated test `backend/tests/test_issue_117_uat_gate.py` verifies parsing, expected matching counts, exception identities, the human-approval boundary, balanced accounting, stable idempotency identity, duplicate lookup before create, and the absence of automatic `action_post`.

The existing regression `backend/tests/test_bank_posting_idempotency.py` is part of the same dedicated CI gate.

Automated result:

- Dependency installation: **PASS**
- `tests/test_issue_117_uat_gate.py`: **PASS**
- `tests/test_bank_posting_idempotency.py`: **PASS**
- Workflow step `Run Issue 117 reconciliation and retry evidence`: **PASS**
- Run ID: `34021020518`

## 3. Live isolated Odoo evidence

Live UAT ran only against the isolated Railway Odoo service in `staging-demo-buyer`.

| Evidence | Verified result |
|---|---|
| Release identity | commit `f498d229003dfed89094dff667dc566621aeb9d8`; runner deployment `f795d055-593d-41c8-b6a4-911d30e295c8` |
| Odoo scope | database `bob_uat_117`; company `BOB UAT 117 SAR` ID `3`; journal ID `16`; synthetic non-production data only |
| Currency | SAR |
| First write | **PASS** — status `success`; Odoo move ID `57` |
| Retry | **PASS** — status `duplicate_prevented`; same move reused |
| Duplicate count | **PASS** — `move_count = 1` |
| Move state | `draft`; no automatic `action_post` |
| Accounting | **PASS** — Debit SAR 57.50 = Credit SAR 57.50 |
| Bank account | code `101118`, ID `233` |
| Bank charges account | code `601118`, ID `234` |
| Idempotency | key `62eaca83ef571cc6e4d782eb9e44afd00e7e196300e08779c012052ae634ce8c` |
| Audit sequence 1 | `odoo_bank_reconciliation_entry_created`, sequence `1` |
| Audit sequence 2 | `odoo_duplicate_prevented`, sequence `2` |
| Audit chaining | second event `previous_hash` equals first event hash |
| Safety | no production Odoo database, credential, or customer document used |

Audit hashes retained from the Railway execution:

- create event hash: `a917ddf86bb28de3fa49f826a6e3c9be3fe285941c55d799f6cf487f2e804987`
- duplicate-prevented event hash: `4c154ccfc553d8bf121765449ab22642212f208e5058e983d332a0d489585307`

## 4. Security configuration evidence

Railway staging now uses the staging application profile rather than pretending to be production. Production Railway environments still require `APP_ENV=production`.

ERP outbound access remains fail-closed and is restricted to the isolated Odoo UAT target:

- allowed hosts: `odoo-uat`, `odoo-uat.railway.internal`
- allowed port: `8069`
- private CIDRs required for Railway dual-stack internal DNS: `10.0.0.0/8`, `fc00::/7`
- HTTP is allowed only under the non-production staging profile for encrypted Railway private-network traffic.

## 5. Sign-off decision

- Synthetic reconciliation gate: **PASS**
- Human-approval contract: **PASS**
- Idempotency contract: **PASS**
- Isolated live Odoo First Write: **PASS**
- Identical Retry duplicate prevention: **PASS**
- Verify exactly one Odoo move: **PASS**
- Accounting balance: **PASS**
- Ordered immutable audit evidence: **PASS**
- Production/customer-data isolation: **PASS**
- Finance-owner authorization to close the UAT gate: explicit task instruction to close the gate after successful evidence execution.

**Issue #117 UAT checkbox may be closed.**
