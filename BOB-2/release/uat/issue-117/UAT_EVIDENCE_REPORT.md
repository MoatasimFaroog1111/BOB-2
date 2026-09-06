# Issue #117 — GuardianAI Reconcile for Odoo UAT Evidence

**Scope:** first paid-pilot release gate for bank reconciliation  
**Data class:** synthetic, non-customer, SAR  
**Test period:** August 2026  
**Branch:** `uat/issue-117-pilot-gate`  
**Tested commit:** `076f2c7a0d0433c9c4e8d451334f63a1aa559693`  
**GitHub Actions run:** `34021020518` — `Issue 117 UAT gate`  
**Status:** AUTOMATED EVIDENCE PASSED; LIVE ODOO SIGN-OFF REQUIRED

## 1. Scenario

The synthetic statement contains six transactions and the synthetic Odoo ledger contains six transactions. The expected result is:

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

The dedicated test `backend/tests/test_issue_117_uat_gate.py` verifies:

1. Statement and ledger parsing.
2. Expected matching counts and exception identities.
3. Balanced accounting proposal for the unmatched bank fee.
4. Human-approval boundary occurs before any Odoo `account.move.create` call.
5. Same source row generates the same idempotency key on retry.
6. Duplicate lookup and `duplicate_prevented` return occur before Odoo move creation.
7. The bank-posting boundary does not call `action_post`; creation remains safer than automatic financial posting.

The existing regression `backend/tests/test_bank_posting_idempotency.py` is part of the same dedicated CI gate.

Dedicated workflow: `.github/workflows/issue-117-uat-gate.yml`.

Automated result for commit `076f2c7a0d0433c9c4e8d451334f63a1aa559693`:

- Dependency installation: **PASS**
- `tests/test_issue_117_uat_gate.py`: **PASS**
- `tests/test_bank_posting_idempotency.py`: **PASS**
- Workflow step `Run Issue 117 reconciliation and retry evidence`: **PASS**
- Run ID: `34021020518`

## 3. Required live non-production Odoo evidence

The Issue #117 UAT checkbox MUST NOT be closed from synthetic tests alone. Before sign-off, run the same scenario against a non-production Odoo database and retain all of the following:

| Evidence | Required proof |
|---|---|
| Release identity | Exact tested commit SHA and Railway deployment ID |
| Odoo scope | Non-production database name, company ID and bank journal ID; no secrets |
| Reconciliation | Screenshot/export showing 5 matched, 1 statement-only, 1 ledger-only |
| Human review | Bank fee is not written until an authorized reviewer approves it |
| First write | Approved bank-fee proposal creates exactly one Odoo `account.move` |
| Retry | Identical request returns/reuses the same move and creates no second move |
| Accounting | Debit = Credit = SAR 57.50; correct date, journal and company |
| Audit | Approval, first create and duplicate-prevented events are attributable and ordered |
| Safety | No production credential or customer document is used |

## 4. Current live-environment observation

At preparation time, the Railway environment `staging-demo-buyer` exists, but the BOB-2 service has no application configuration/deployment in that environment and no UAT Odoo connection variables are available there. Therefore a genuine live-Odoo execution cannot be truthfully recorded as passed yet.

This is a **blocking evidence gap**, not a product-code failure. Do not mark UAT-15 or the Issue #117 `تشغيل UAT كامل على Odoo تجريبي وحفظ الأدلة` checkbox as complete until the table in section 3 is populated from a real non-production run.

## 5. Sign-off decision

- Synthetic reconciliation gate: **PASS**
- Human-approval contract: **PASS**
- Idempotency contract: **PASS**
- Live non-production Odoo run: **BLOCKED — environment/connection not configured**
- Issue #117 UAT checkbox: **DO NOT CLOSE YET**

The live run must populate immutable Odoo/Railway evidence and receive the finance-owner sign-off required by `release/ACCOUNTING_UAT_SIGNOFF.md` before the UAT checkbox is closed.
