# Accounting User Acceptance Test and Sign-off

**Release:** ____________________  
**Environment:** ____________________  
**Customer / pilot entity:** ____________________  
**Test period:** ____________________  

## Status rule

This document is **READY FOR SIGN-OFF**, not signed. Automated tests cannot replace acceptance by an authorized finance professional using the customer's chart of accounts, tax configuration, approval matrix and real operating procedures.

The product must not be described as accounting-UAT approved until every mandatory scenario below is evidenced and the three signatures at the end are completed.

## Entry criteria

- Release commit is immutable and recorded.
- Backend, PostgreSQL, frontend, tenant isolation and security workflows are green.
- A non-production customer database and representative test data are available.
- Opening balances and the chart of accounts are approved by the customer.
- No production posting credential is used without written authorization.

## Mandatory scenarios

| ID | Scenario | Expected result | Evidence | Result |
|---|---|---|---|---|
| UAT-01 | Balanced manual journal | Total debit equals total credit; correct date, journal, partner and description | Entry ID and screenshot | ☐ Pass ☐ Fail |
| UAT-02 | Unbalanced journal | Proposal or posting is rejected with no partial entry | API/UI evidence | ☐ Pass ☐ Fail |
| UAT-03 | Duplicate source document | Duplicate is detected or requires explicit authorized override | Document hashes and audit event | ☐ Pass ☐ Fail |
| UAT-04 | Vendor invoice extraction | Supplier, invoice number, date, currency, net, tax and gross are compared to the source | Source document and comparison sheet | ☐ Pass ☐ Fail |
| UAT-05 | Customer invoice extraction | Customer and monetary fields match the source; no automatic posting without approval | Source and audit trail | ☐ Pass ☐ Fail |
| UAT-06 | Credit note | Sign, reference to original invoice and ledger effect are correct | Journal and ledger extract | ☐ Pass ☐ Fail |
| UAT-07 | Payment and allocation | Bank/payment amount is matched to the correct open item without cross-tenant data | Reconciliation evidence | ☐ Pass ☐ Fail |
| UAT-08 | Bank reconciliation | Opening balance + movements = closing balance; unmatched items remain visible | Bank statement and reconciliation report | ☐ Pass ☐ Fail |
| UAT-09 | Multi-currency entry | Transaction currency, company currency and exchange difference are correct | Rate source and journal | ☐ Pass ☐ Fail |
| UAT-10 | VAT treatment | Tax code, taxable base and tax amount agree with the approved customer tax configuration | Tax report comparison | ☐ Pass ☐ Fail |
| UAT-11 | Period lock | Unauthorized posting into a locked period is rejected | Lock settings and rejection | ☐ Pass ☐ Fail |
| UAT-12 | Reversal / cancellation | Original entry remains auditable and reversal posts to the approved date | Original and reversal IDs | ☐ Pass ☐ Fail |
| UAT-13 | Approval segregation | Preparer cannot approve/post beyond assigned permissions | Two-user evidence | ☐ Pass ☐ Fail |
| UAT-14 | Tenant isolation | Users of organization A cannot read or mutate organization B records | Access test evidence | ☐ Pass ☐ Fail |
| UAT-15 | Odoo posting | Approved proposal creates exactly one correct Odoo move; retry does not duplicate | Odoo move and idempotency evidence | ☐ Pass ☐ Fail |
| UAT-16 | Audit trail | Creation, review, approval, posting, failure and reversal events are attributable and ordered | Audit export | ☐ Pass ☐ Fail |
| UAT-17 | Backup recovery | Restored environment reproduces the selected journals and audit-chain head | Restore report | ☐ Pass ☐ Fail |
| UAT-18 | Financial report tie-out | Trial balance and selected ledgers agree with the independent expected totals | Signed comparison workbook | ☐ Pass ☐ Fail |

## Monetary tolerances

No unexplained difference is accepted. Rounding tolerances must be defined by currency and customer policy before testing:

| Currency | Minor unit / tolerance | Approved by |
|---|---:|---|
| SAR | __________ | __________ |
| USD | __________ | __________ |
| Other | __________ | __________ |

## Defects and concessions

| Defect ID | Severity | Description | Resolution / approved concession | Owner | Closure evidence |
|---|---|---|---|---|---|
| | | | | | |

Critical or high defects affecting monetary accuracy, authorization, tenant isolation, auditability, backup recovery or tax handling block production release. A concession cannot waive a legal or security requirement.

## Sign-off

By signing, the reviewers confirm that the stated release was tested in the stated environment and that evidence is retained. This is not a guarantee of future results or a replacement for continuing reconciliations and controls.

**Customer Finance Owner**  
Name: ____________________  
Title: ____________________  
Signature: ____________________  
Date: ____________________

**Implementation / Product Owner**  
Name: ____________________  
Signature: ____________________  
Date: ____________________

**Independent Reviewer / Internal Audit**  
Name: ____________________  
Signature: ____________________  
Date: ____________________
