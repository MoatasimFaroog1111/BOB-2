#!/usr/bin/env python3
"""Runtime smoke test for the locked persisted accounting model.

Reads one validation INPUT only, never its target, and verifies Load -> Predict -> Gate.
No ERP mutation, retraining, threshold tuning, or test-set read occurs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.ml.accounting_intelligence.contracts import AccountingReferenceCatalog
from app.ml.accounting_intelligence.persisted_bundle import PersistedAccountingPredictor
from app.ml.accounting_intelligence.prediction_gate import AccountingPredictionGate


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def catalog(root: Path) -> AccountingReferenceCatalog:
    records = root / "records"
    return AccountingReferenceCatalog(
        accounts=tuple(load_jsonl(records / "account_account.jsonl")),
        journals=tuple(load_jsonl(records / "account_journal.jsonl")),
        taxes=tuple(load_jsonl(records / "account_tax.jsonl")),
        partners=tuple(load_jsonl(records / "res_partner.jsonl")),
        analytic_accounts=tuple(load_jsonl(records / "account_analytic_account.jsonl")),
        products=tuple(load_jsonl(records / "product_product.jsonl")),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/data/storage/odoo-training-dataset")
    args = parser.parse_args()
    root = Path(args.root)

    validation_path = root / "training" / "supervised_v1" / "validation.jsonl"
    with validation_path.open(encoding="utf-8") as handle:
        row = json.loads(next(line for line in handle if line.strip()))

    inp = row.get("input") or {}
    text = str(inp.get("combined_text") or "").strip()
    documents = [
        {
            "extension": doc.get("extension"),
            "mime": doc.get("mime"),
            "extractor": doc.get("extractor"),
            "ocr_pages": int(doc.get("ocr_pages") or 0),
        }
        for doc in (inp.get("documents") or [])
    ]
    if not text:
        raise RuntimeError("Smoke validation input has no extracted text.")

    predictor = PersistedAccountingPredictor()
    status = predictor.loader.status()
    print("BUNDLE_STATUS =", json.dumps(status, ensure_ascii=False))
    if not status.get("verified"):
        raise RuntimeError("Locked persisted bundle verification failed.")

    prediction = predictor.predict(
        text=text,
        catalog=catalog(root),
        documents=documents,
        top_k=5,
    )
    gate = AccountingPredictionGate().evaluate(prediction, amount=1.0)

    compact = {
        "model_version": prediction["model_version"],
        "bundle_sha256": prediction["bundle_sha256"],
        "move_type": prediction["move_type"][:3],
        "journals": prediction["journals"][:3],
        "debit_accounts": prediction["debit_accounts"][:5],
        "credit_accounts": prediction["credit_accounts"][:5],
        "taxes": prediction["taxes"][:3],
        "analytic_accounts": prediction["analytic_accounts"][:5],
        "confidence_proxy": prediction["confidence_proxy"],
        "decision_gate": gate,
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    print("TRAINING_DURING_SMOKE=FALSE")
    print("TEST_SET_READ_DURING_SMOKE=FALSE")
    print("ERP_MUTATION_DURING_SMOKE=FALSE")
    print("PERSISTED_ACCOUNTING_INFERENCE_SMOKE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
