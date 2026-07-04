# GMAWS to BOB-2 Integration

## Purpose

This integration brings the useful part of the uploaded GMAWS project into BOB-2: a multi-agent workflow pattern for accounting and audit work.

The full GMAWS robotics stack was not copied into BOB-2 because BOB-2 is an accounting, audit, OCR, ERP, and compliance platform. GMAWS includes robot-design and simulation packages that are not needed for accounting workflows and may create installation/version conflicts.

## What was integrated

Added a lightweight accounting multi-agent orchestrator:

- `IntakeAgent`: classifies accounting document type and language.
- `DocumentControlAgent`: checks required accounting evidence such as date, amount, and party.
- `TaxAgent`: detects KSA VAT signals, VAT numbers, and possible 15% VAT relationships.
- `JournalAgent`: prepares draft accounting treatment without ERP posting.
- `ReviewerAgent`: acts as audit safety gate and flags manual review points.

## New API endpoints

Base path:

```text
/api/v1/agents
```

Capabilities:

```http
GET /api/v1/agents/capabilities
```

Run workflow:

```http
POST /api/v1/agents/run-accounting-workflow
```

Example request:

```json
{
  "source_type": "invoice",
  "organization_id": 1,
  "language": "auto",
  "text": "Tax Invoice INV/2026/0001 Supplier: ABC Date: 2026-07-04 Subtotal SAR 1000 VAT 15% SAR 150 Total SAR 1150"
}
```

## Version and dependency conflict handling

BOB-2 existing backend stack is preserved:

- FastAPI >=0.115,<1
- Uvicorn >=0.30,<1
- Pydantic >=2.7,<3
- SQLAlchemy >=2,<3
- Python 3.11+

GMAWS compatible but non-heavy optional packages were isolated into:

```text
backend/requirements-gmaws-compatible.txt
```

The following robotics/simulation packages were intentionally not added:

- `pybullet`
- `trimesh`
- `numpy>=1.26,<2` pin from GMAWS

This keeps BOB-2 stable on Windows/WSL and avoids unnecessary conflicts with accounting, OCR, embeddings, and database packages.

## Safety rule

The multi-agent workflow never posts to ERP automatically. It returns suggestions and review points only:

```json
{
  "auto_posted_to_erp": false,
  "approval_required": true
}
```

This matches the audit-safe direction already used by the existing `AccountingAIMatchingService`.

## Recommended next step

After this branch passes tests, the next integration phase can connect the multi-agent workflow to:

1. OCR upload results.
2. Bank reconciliation results.
3. Existing Accounting AI matching embeddings.
4. Odoo XML-RPC posting workflow, still behind explicit approval.
