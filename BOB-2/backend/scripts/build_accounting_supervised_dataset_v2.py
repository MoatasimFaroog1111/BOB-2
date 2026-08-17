#!/usr/bin/env python3
"""Build supervised accounting dataset v2 with audited historical analytic-ID normalization.

This wrapper preserves the v1 builder and source export unchanged. It only normalizes
three known historical target references whose current analytic-account equivalent is
supported by the exported accounting history:

- historical analytic ID 5 -> current analytic ID 2 (Head Office)
- historical analytic ID 6 -> current analytic ID 2 (Head Office)

The original IDs remain visible as ``historical_source_id`` in enriched target objects.
This keeps the transformation auditable while preventing obsolete Odoo database IDs
from becoming unresolved training labels.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import build_accounting_supervised_dataset as base

HISTORICAL_ANALYTIC_ID_MAP: dict[int, int] = {
    5: 2,
    6: 2,
}

_ORIGINAL_CATALOG_REF = base.catalog_ref
_ORIGINAL_ENRICH_TARGET = base.enrich_target


def _is_analytic_catalog_request(fields: tuple[str, ...]) -> bool:
    return "plan_id" in fields


def mapped_catalog_ref(
    ident: int | None,
    catalog: dict[int, dict[str, Any]],
    fields: tuple[str, ...],
    unresolved: set[int],
) -> dict[str, Any] | None:
    """Resolve audited historical analytic IDs to their current catalog record."""
    source_ident = ident
    if (
        ident is not None
        and _is_analytic_catalog_request(fields)
        and ident in HISTORICAL_ANALYTIC_ID_MAP
    ):
        mapped_ident = HISTORICAL_ANALYTIC_ID_MAP[ident]
        if mapped_ident in catalog:
            result = _ORIGINAL_CATALOG_REF(mapped_ident, catalog, fields, unresolved)
            if result is not None:
                result = dict(result)
                result["historical_source_id"] = source_ident
                result["historical_remap"] = True
            return result

    return _ORIGINAL_CATALOG_REF(ident, catalog, fields, unresolved)


def _remap_distribution_key(key: Any) -> tuple[str, bool]:
    parts: list[str] = []
    changed = False
    for raw in str(key).split(","):
        token = raw.strip()
        try:
            ident = int(token)
        except ValueError:
            parts.append(token)
            continue

        mapped = HISTORICAL_ANALYTIC_ID_MAP.get(ident, ident)
        if mapped != ident:
            changed = True
        parts.append(str(mapped))

    return ",".join(parts), changed


def normalize_analytic_distribution(value: Any) -> tuple[Any, list[dict[str, Any]]]:
    if not isinstance(value, dict):
        return value, []

    normalized: dict[str, Any] = {}
    changes: list[dict[str, Any]] = []

    for key, percentage in value.items():
        new_key, changed = _remap_distribution_key(key)
        if changed:
            changes.append({
                "source_key": str(key),
                "normalized_key": new_key,
                "value": percentage,
            })

        if new_key not in normalized:
            normalized[new_key] = percentage
        else:
            existing = normalized[new_key]
            if isinstance(existing, (int, float)) and isinstance(percentage, (int, float)):
                normalized[new_key] = max(existing, percentage)
            else:
                normalized[new_key] = percentage

    return normalized, changes


def mapped_enrich_target(
    example: dict[str, Any],
    catalogs: dict[str, dict[int, dict[str, Any]]],
    unresolved: dict[str, set[int]],
) -> dict[str, Any]:
    result = _ORIGINAL_ENRICH_TARGET(example, catalogs, unresolved)

    for line in result.get("lines", []):
        normalized, changes = normalize_analytic_distribution(
            line.get("analytic_distribution")
        )
        line["analytic_distribution"] = normalized
        if changes:
            line["historical_analytic_remaps"] = changes

    return result


def _root_from_cli() -> Path:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--root", default="/data/storage/odoo-training-dataset")
    args, _ = parser.parse_known_args()
    return Path(args.root)


def main() -> int:
    base.catalog_ref = mapped_catalog_ref
    base.enrich_target = mapped_enrich_target

    code = base.main()

    root = _root_from_cli()
    manifest_path = root / "training" / "supervised_v1" / "manifest.json"
    if not manifest_path.is_file():
        print("HISTORICAL_ANALYTIC_REMAP=REVIEW")
        return code or 3

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["historical_analytic_id_remap"] = {
        str(source): {
            "current_id": target,
            "current_name": "Head Office",
            "basis": "audited historical-frequency comparison",
        }
        for source, target in sorted(HISTORICAL_ANALYTIC_ID_MAP.items())
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    unresolved = manifest.get("unresolved_ids") or {}
    if unresolved:
        print("HISTORICAL_ANALYTIC_REMAP=REVIEW")
        print("UNRESOLVED_IDS =", json.dumps(unresolved, ensure_ascii=False))
        return code or 3

    print("HISTORICAL_ANALYTIC_REMAP=PASS")
    print("HISTORICAL_ANALYTIC_ID_MAP =", HISTORICAL_ANALYTIC_ID_MAP)
    print("UNRESOLVED_IDS = {}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
