# ZATCA E-Invoicing Scope and Test Matrix

## Current release classification

BOB-2 is an accounting-assistance, document-processing and ERP-integration application. The reviewed release does **not** independently generate, cryptographically stamp, clear, report or archive ZATCA e-invoices. Any e-invoice issued through an integrated ERP remains the responsibility of the ERP's approved configuration and the taxable person.

Therefore:

- Do not market BOB-2 as **ZATCA certified**, **ZATCA approved**, or an independent e-invoicing solution.
- The current release may pass the **integration-boundary scenarios** below.
- The full e-invoicing scenarios are **not applicable until invoice issuance is implemented**. Once implemented, all items marked `FUTURE GATE` become mandatory release blockers.

Official reference baseline must be taken from ZATCA's current Technical Requirements & Specifications and E-Invoicing Developer Portal before each release. The release owner must record the document versions and access date below.

**Technical specification/version:** ____________________  
**Security requirements/version:** ____________________  
**Developer portal test suite/version:** ____________________  
**Reviewed on:** ____________________

## Current integration-boundary scenarios

| ID | Scenario | Expected result | Status |
|---|---|---|---|
| ZB-01 | User asks BOB-2 to issue a ZATCA invoice directly | System does not claim issuance or certification; directs the operation through the configured ERP/human-approved workflow | ☐ Pass ☐ Fail |
| ZB-02 | Imported tax invoice document | Original file and extracted fields remain linked; extraction does not alter the legal source document | ☐ Pass ☐ Fail |
| ZB-03 | VAT amount extraction | Extracted taxable amount, VAT and total are presented for verification, not silently treated as authoritative | ☐ Pass ☐ Fail |
| ZB-04 | Odoo posting approval | No financial posting occurs without an authorized approval and tenant-scoped ERP credential | ☐ Pass ☐ Fail |
| ZB-05 | Duplicate invoice | Duplicate source hash/reference is detected or explicitly reviewed before posting | ☐ Pass ☐ Fail |
| ZB-06 | Failure or timeout from ERP | No false success is returned and no duplicate retry is created | ☐ Pass ☐ Fail |
| ZB-07 | Audit evidence | User, tenant, source hash, proposal, approval and ERP result are traceable without exposing credentials | ☐ Pass ☐ Fail |
| ZB-08 | Marketing and UI claims | No screen, document or website states ZATCA certification/approval without formal evidence | ☐ Pass ☐ Fail |

Passing ZB-01 through ZB-08 means only that the current product respects its non-issuer boundary. It is not a ZATCA product certification.

## FUTURE GATE — mandatory before independent invoice issuance

These scenarios become mandatory if BOB-2 creates or submits e-invoices itself:

| ID | Required capability | Evidence required |
|---|---|---|
| ZE-01 | Correct simplified/standard invoice classification | Test cases and approved business rules |
| ZE-02 | Required XML structure and business rules | Validator output for every supported invoice type |
| ZE-03 | UUID, invoice counter and previous-invoice hash continuity | Sequence and tamper tests |
| ZE-04 | Cryptographic stamp/signature and certificate lifecycle | Developer portal evidence and key-management review |
| ZE-05 | QR code content and encoding | Independent decoded comparison |
| ZE-06 | Standard invoice clearance workflow | Sandbox requests/responses and failure handling |
| ZE-07 | Simplified invoice reporting workflow | Sandbox requests/responses and reporting-window controls |
| ZE-08 | Credit/debit note references | Valid XML and business linkage to original invoice |
| ZE-09 | Cancellation/rejection/retry idempotency | No duplicate invoice or counter corruption |
| ZE-10 | Arabic and required seller/buyer/tax fields | Golden-file comparisons |
| ZE-11 | Time, timezone and timestamp controls | Clock-skew and boundary tests |
| ZE-12 | Immutable archive and retention | Restore test and access-control evidence |
| ZE-13 | Security requirements | Threat model, secrets/key custody, penetration test and remediation |
| ZE-14 | Developer portal conformance | Successful current sandbox/portal validation evidence |
| ZE-15 | Production onboarding | Taxpayer-specific authorization and operational acceptance |

## Release decision

- **Current ERP-assistance scope:** ☐ PASS ☐ FAIL
- **Independent e-invoicing scope:** ☐ NOT IMPLEMENTED ☐ PASS after all FUTURE GATE evidence
- Reviewer: ____________________
- Date: ____________________

No automated workflow may mark this document signed or certified. The release evidence must be reviewed by the product owner, the customer's tax owner and an appropriately qualified Saudi tax/e-invoicing adviser.
