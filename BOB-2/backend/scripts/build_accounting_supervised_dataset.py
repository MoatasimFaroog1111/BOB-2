#!/usr/bin/env python3
"""Build leakage-safe supervised accounting examples from document features + Odoo targets.

Input at inference time is intentionally attachment-derived only:
- extracted/OCR text;
- document metadata and extraction-quality features.

Odoo accounting truth remains exclusively in the target. Catalog IDs are enriched with
stable business identifiers such as account codes and names so the learner does not
memorize instance-local numeric IDs alone.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import zlib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "accounting-supervised-v1.0.0"
EXPECTED_TOTAL = 5719


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def m2o_id(value: Any) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    if value in (None, False, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def id_list(values: Any) -> list[int]:
    out: list[int] = []
    for value in values or []:
        ident = m2o_id(value)
        if ident is not None:
            out.append(ident)
    return sorted(set(out))


def load_catalog(path: Path) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            try:
                rows[int(row["id"])] = row
            except (KeyError, TypeError, ValueError):
                continue
    return rows


def catalog_ref(
    ident: int | None,
    catalog: dict[int, dict[str, Any]],
    fields: tuple[str, ...],
    unresolved: set[int],
) -> dict[str, Any] | None:
    if ident is None:
        return None
    row = catalog.get(ident)
    if row is None:
        unresolved.add(ident)
        return {"id": ident, "unresolved": True}
    result: dict[str, Any] = {"id": ident}
    for field in fields:
        if field in row and row[field] not in (None, False, ""):
            result[field] = row[field]
    return result


def load_split_map(root: Path) -> tuple[dict[str, str], dict[str, set[str]]]:
    split_dir = root / "training" / "splits_balanced"
    split_map: dict[str, str] = {}
    split_shas: dict[str, set[str]] = {}
    for split in ("train", "validation", "test"):
        path = split_dir / f"{split}_index.jsonl"
        shas: set[str] = set()
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                eid = str(row["example_id"])
                if eid in split_map:
                    raise RuntimeError(f"Example assigned to multiple splits: {eid}")
                split_map[eid] = split
                shas.update(str(x) for x in (row.get("attachment_sha256") or []))
        split_shas[split] = shas
    return split_map, split_shas


class FeatureStore:
    def __init__(self, db_path: Path) -> None:
        self.db = sqlite3.connect(db_path)
        self.cache: dict[str, dict[str, Any]] = {}

    def get(self, sha256: str) -> dict[str, Any]:
        cached = self.cache.get(sha256)
        if cached is not None:
            return cached

        row = self.db.execute(
            """
            SELECT relative_path,mime,name,extension,size_bytes,status,extractor,
                   page_count,embedded_pages,ocr_pages,ocr_mean_conf,
                   char_count,line_count,arabic_char_count,latin_char_count,
                   digit_char_count,text_sha256,text_zlib,error
            FROM document_features WHERE sha256=?
            """,
            (sha256,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Feature cache missing SHA: {sha256}")
        if row[5] != "success":
            raise RuntimeError(f"Feature cache SHA is not successful: {sha256}: {row[18]}")

        text = ""
        if row[17] is not None:
            text = zlib.decompress(row[17]).decode("utf-8", errors="replace")

        feature = {
            "sha256": sha256,
            "relative_path": row[0],
            "mime": row[1],
            "name": row[2],
            "extension": row[3],
            "size_bytes": int(row[4] or 0),
            "extractor": row[6],
            "page_count": int(row[7] or 0),
            "embedded_pages": int(row[8] or 0),
            "ocr_pages": int(row[9] or 0),
            "ocr_mean_conf": row[10],
            "char_count": int(row[11] or 0),
            "line_count": int(row[12] or 0),
            "arabic_char_count": int(row[13] or 0),
            "latin_char_count": int(row[14] or 0),
            "digit_char_count": int(row[15] or 0),
            "text_sha256": row[16],
            "text": text,
        }
        self.cache[sha256] = feature
        return feature

    def close(self) -> None:
        self.db.close()


def attachment_sha(attachment: dict[str, Any]) -> str | None:
    download = attachment.get("download") or {}
    value = download.get("sha256")
    return str(value) if value else None


def enrich_target(
    example: dict[str, Any],
    catalogs: dict[str, dict[int, dict[str, Any]]],
    unresolved: dict[str, set[int]],
) -> dict[str, Any]:
    target = example.get("target", {})
    journal_entry = target.get("journal_entry", {})
    move = journal_entry.get("move", {})
    lines = journal_entry.get("lines", [])
    labels = target.get("labels", {})

    accounts = catalogs["accounts"]
    journals = catalogs["journals"]
    taxes = catalogs["taxes"]
    analytics = catalogs["analytics"]
    partners = catalogs["partners"]
    currencies = catalogs["currencies"]
    products = catalogs["products"]

    move_out = {
        "move_type": move.get("move_type"),
        "date": move.get("date"),
        "invoice_date": move.get("invoice_date"),
        "invoice_date_due": move.get("invoice_date_due"),
        "ref": move.get("ref"),
        "invoice_origin": move.get("invoice_origin"),
        "payment_reference": move.get("payment_reference"),
        "narration": move.get("narration"),
        "amount_untaxed": move.get("amount_untaxed"),
        "amount_tax": move.get("amount_tax"),
        "amount_total": move.get("amount_total"),
        "amount_residual": move.get("amount_residual"),
        "payment_state": move.get("payment_state"),
        "journal": catalog_ref(
            m2o_id(move.get("journal_id")), journals,
            ("code", "name", "type", "currency_id"), unresolved["journals"]
        ),
        "partner": catalog_ref(
            m2o_id(move.get("partner_id")), partners,
            ("name", "display_name", "vat", "company_type", "supplier_rank", "customer_rank"),
            unresolved["partners"],
        ),
        "currency": catalog_ref(
            m2o_id(move.get("currency_id")), currencies,
            ("name", "symbol", "rounding", "decimal_places"), unresolved["currencies"]
        ),
    }

    enriched_lines: list[dict[str, Any]] = []
    for line in lines:
        tax_ids = id_list(line.get("tax_ids"))
        analytic_ids: set[int] = set()
        analytic_distribution = line.get("analytic_distribution") or {}
        if isinstance(analytic_distribution, dict):
            for key in analytic_distribution:
                for part in str(key).split(","):
                    try:
                        analytic_ids.add(int(part.strip()))
                    except ValueError:
                        pass

        enriched_lines.append({
            "name": line.get("name"),
            "ref": line.get("ref"),
            "account": catalog_ref(
                m2o_id(line.get("account_id")), accounts,
                ("code", "name", "account_type", "reconcile"), unresolved["accounts"]
            ),
            "partner": catalog_ref(
                m2o_id(line.get("partner_id")), partners,
                ("name", "display_name", "vat"), unresolved["partners"]
            ),
            "currency": catalog_ref(
                m2o_id(line.get("currency_id")), currencies,
                ("name", "symbol"), unresolved["currencies"]
            ),
            "debit": line.get("debit"),
            "credit": line.get("credit"),
            "balance": line.get("balance"),
            "amount_currency": line.get("amount_currency"),
            "quantity": line.get("quantity"),
            "price_unit": line.get("price_unit"),
            "discount": line.get("discount"),
            "price_subtotal": line.get("price_subtotal"),
            "price_total": line.get("price_total"),
            "product": catalog_ref(
                m2o_id(line.get("product_id")), products,
                ("name", "display_name", "default_code", "categ_id"), unresolved["products"]
            ),
            "taxes": [
                catalog_ref(tid, taxes, ("name", "description", "amount", "amount_type", "type_tax_use"), unresolved["taxes"])
                for tid in tax_ids
            ],
            "tax_line": catalog_ref(
                m2o_id(line.get("tax_line_id")), taxes,
                ("name", "description", "amount", "amount_type", "type_tax_use"), unresolved["taxes"]
            ),
            "analytic_distribution": analytic_distribution,
            "analytic_accounts": [
                catalog_ref(aid, analytics, ("code", "name", "plan_id"), unresolved["analytics"])
                for aid in sorted(analytic_ids)
            ],
        })

    debit_ids = id_list(labels.get("debit_account_ids"))
    credit_ids = id_list(labels.get("credit_account_ids"))
    label_tax_ids = id_list(labels.get("tax_ids"))
    label_analytic_ids = id_list(labels.get("analytic_account_ids"))

    return {
        "move": move_out,
        "lines": enriched_lines,
        "labels": {
            "debit_accounts": [
                catalog_ref(x, accounts, ("code", "name", "account_type"), unresolved["accounts"])
                for x in debit_ids
            ],
            "credit_accounts": [
                catalog_ref(x, accounts, ("code", "name", "account_type"), unresolved["accounts"])
                for x in credit_ids
            ],
            "taxes": [
                catalog_ref(x, taxes, ("name", "description", "amount", "amount_type", "type_tax_use"), unresolved["taxes"])
                for x in label_tax_ids
            ],
            "analytic_accounts": [
                catalog_ref(x, analytics, ("code", "name", "plan_id"), unresolved["analytics"])
                for x in label_analytic_ids
            ],
            "total_debit": labels.get("total_debit"),
            "total_credit": labels.get("total_credit"),
            "balanced": bool(labels.get("balanced")),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/data/storage/odoo-training-dataset")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.root)
    examples_path = root / "training" / "examples.jsonl"
    feature_db = root / "features" / "document_features.sqlite3"
    output_dir = root / "training" / "supervised_v1"
    output_dir.mkdir(parents=True, exist_ok=True)

    split_map, split_shas = load_split_map(root)

    catalogs = {
        "accounts": load_catalog(root / "records" / "account_account.jsonl"),
        "journals": load_catalog(root / "records" / "account_journal.jsonl"),
        "taxes": load_catalog(root / "records" / "account_tax.jsonl"),
        "analytics": load_catalog(root / "records" / "account_analytic_account.jsonl"),
        "partners": load_catalog(root / "records" / "res_partner.jsonl"),
        "currencies": load_catalog(root / "records" / "res_currency.jsonl"),
        "products": load_catalog(root / "records" / "product_product.jsonl"),
    }

    unresolved: dict[str, set[int]] = defaultdict(set)
    store = FeatureStore(feature_db)
    files = {
        split: (output_dir / f"{split}.jsonl").open("w", encoding="utf-8")
        for split in ("train", "validation", "test")
    }

    counts = Counter()
    move_types: dict[str, Counter[str]] = defaultdict(Counter)
    doc_refs = Counter()
    unique_shas: dict[str, set[str]] = defaultdict(set)
    missing_split: list[str] = []
    unbalanced: list[str] = []
    total_text_chars = 0

    try:
        with examples_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                example = json.loads(line)
                eid = str(example["example_id"])
                split = split_map.get(eid)
                if split is None:
                    missing_split.append(eid)
                    continue

                documents: list[dict[str, Any]] = []
                combined_parts: list[str] = []
                for attachment in example.get("input", {}).get("attachments", []):
                    sha = attachment_sha(attachment)
                    if not sha:
                        continue
                    feature = store.get(sha)
                    documents.append(feature)
                    unique_shas[split].add(sha)
                    doc_refs[split] += 1
                    if feature["text"]:
                        combined_parts.append(
                            f"=== DOCUMENT: {feature['name']} ===\n{feature['text']}"
                        )
                        total_text_chars += len(feature["text"])

                target = enrich_target(example, catalogs, unresolved)
                if not target["labels"]["balanced"]:
                    unbalanced.append(eid)

                record = {
                    "schema_version": SCHEMA_VERSION,
                    "example_id": eid,
                    "split": split,
                    "input": {
                        "documents": documents,
                        "combined_text": "\n\n".join(combined_parts),
                    },
                    "target": target,
                    "provenance": example.get("provenance", {}),
                }
                files[split].write(
                    json.dumps(record, ensure_ascii=False, default=str, separators=(",", ":")) + "\n"
                )
                counts[split] += 1
                move_type = str(target["move"].get("move_type") or "UNKNOWN")
                move_types[split][move_type] += 1
    finally:
        for handle in files.values():
            handle.close()
        store.close()

    overlaps = {
        "train_validation": len(split_shas["train"] & split_shas["validation"]),
        "train_test": len(split_shas["train"] & split_shas["test"]),
        "validation_test": len(split_shas["validation"] & split_shas["test"]),
    }

    file_bytes = {
        split: (output_dir / f"{split}.jsonl").stat().st_size
        for split in ("train", "validation", "test")
    }
    total = sum(counts.values())

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "input_contract": "attachment-derived features only; Odoo truth is target-only",
        "total_examples": total,
        "splits": {
            split: {
                "examples": counts[split],
                "document_references": doc_refs[split],
                "unique_document_sha": len(unique_shas[split]),
                "move_types": dict(move_types[split]),
                "bytes": file_bytes[split],
            }
            for split in ("train", "validation", "test")
        },
        "catalog_sizes": {name: len(rows) for name, rows in catalogs.items()},
        "unresolved_ids": {name: sorted(values) for name, values in unresolved.items() if values},
        "missing_split_examples": missing_split,
        "unbalanced_examples": unbalanced,
        "sha_overlap": overlaps,
        "materialized_text_characters": total_text_chars,
    }

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(manifest, ensure_ascii=False, indent=2))

    integrity_ok = (
        total == EXPECTED_TOTAL
        and counts["train"] == 4575
        and counts["validation"] == 573
        and counts["test"] == 571
        and not missing_split
        and not unbalanced
        and all(v == 0 for v in overlaps.values())
    )
    print("SUPERVISED_DATASET_INTEGRITY=" + ("PASS" if integrity_ok else "REVIEW"))
    print("OUTPUT_DIR =", output_dir)
    print("TOTAL_OUTPUT_MIB =", round(sum(file_bytes.values()) / 1024**2, 2))
    return 0 if integrity_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
