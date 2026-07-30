"""Filtered, fail-soft account.move.line candidate retrieval."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

MAX_CANDIDATE_LINES = 5_000
MAX_RESULTS_PER_QUERY = 1_200
STABLE_LINE_SEARCH_FIELDS = ("name", "ref")
STABLE_MOVE_SEARCH_FIELDS = ("ref", "payment_reference", "narration")
SAFE_LINE_FIELDS = (
    "id",
    "move_id",
    "date",
    "account_id",
    "partner_id",
    "name",
    "ref",
    "debit",
    "credit",
    "balance",
    "company_id",
)


@dataclass(frozen=True)
class CandidateLineResult:
    lines: list[dict[str, Any]]
    successful_queries: int
    skipped_queries: int


def or_terms(field_name: str, terms: list[str]) -> list[Any]:
    leaves = [[field_name, "ilike", term] for term in terms if term]
    if not leaves:
        return []
    if len(leaves) == 1:
        return leaves
    return ["|"] * (len(leaves) - 1) + leaves


def _merge_lines(
    destination: dict[int, dict[str, Any]],
    rows: list[dict[str, Any]],
) -> None:
    for row in rows or []:
        row_id = row.get("id")
        if isinstance(row_id, int):
            destination[row_id] = row


def _safe_line_fields(fields: list[str]) -> list[str]:
    selected = [field for field in SAFE_LINE_FIELDS if field in fields]
    if "id" not in selected:
        selected.insert(0, "id")
    return selected


def _search_read(
    erp: Any,
    *,
    domain: list[Any],
    fields: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    return erp.execute_kw(
        "account.move.line",
        "search_read",
        [domain],
        {
            "fields": fields,
            "order": "date desc, id desc",
            "limit": limit,
        },
    )


def _search_then_read(
    erp: Any,
    *,
    domain: list[Any],
    fields: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    ids = erp.execute_kw(
        "account.move.line",
        "search",
        [domain],
        {
            "order": "date desc, id desc",
            "limit": limit,
        },
    )
    if not ids:
        return []
    rows = erp.execute_kw(
        "account.move.line",
        "read",
        [ids],
        {"fields": fields},
    )
    return rows if isinstance(rows, list) else []


def _run_line_query(
    erp: Any,
    *,
    domain: list[Any],
    fields: list[str],
    destination: dict[int, dict[str, Any]],
) -> bool:
    if not domain or len(destination) >= MAX_CANDIDATE_LINES:
        return False

    limit = min(MAX_RESULTS_PER_QUERY, MAX_CANDIDATE_LINES - len(destination))
    preferred_fields = list(dict.fromkeys(fields))
    safe_fields = _safe_line_fields(preferred_fields)

    try:
        rows = _search_read(
            erp,
            domain=domain,
            fields=preferred_fields,
            limit=limit,
        )
        _merge_lines(destination, rows)
        return True
    except Exception:
        logger.info(
            "Candidate search_read rejected with expanded fields; retrying safe fields: %s",
            domain,
            exc_info=True,
        )

    if safe_fields != preferred_fields:
        try:
            rows = _search_read(
                erp,
                domain=domain,
                fields=safe_fields,
                limit=limit,
            )
            _merge_lines(destination, rows)
            return True
        except Exception:
            logger.info(
                "Candidate search_read rejected with safe fields; retrying search plus read: %s",
                domain,
                exc_info=True,
            )

    try:
        rows = _search_then_read(
            erp,
            domain=domain,
            fields=safe_fields,
            limit=limit,
        )
        _merge_lines(destination, rows)
        return True
    except Exception:
        logger.warning(
            "Candidate query rejected after all fallback strategies: %s",
            domain,
            exc_info=True,
        )
        return False


def read_candidate_lines(
    erp: Any,
    *,
    base_domain: list[Any],
    matched_partner_ids: list[int],
    terms: list[str],
    line_fields: list[str],
    line_metadata: dict[str, dict[str, Any]],
    move_metadata: dict[str, dict[str, Any]],
) -> CandidateLineResult:
    """Read only filtered candidates; never issue an unbounded ledger query."""
    if not base_domain and not matched_partner_ids and not terms:
        return CandidateLineResult([], 0, 0)

    candidates: dict[int, dict[str, Any]] = {}
    successful = 0
    skipped = 0

    if matched_partner_ids:
        ok = _run_line_query(
            erp,
            domain=[*base_domain, ["partner_id", "in", matched_partner_ids]],
            fields=line_fields,
            destination=candidates,
        )
        successful += int(ok)
        skipped += int(not ok)

    for field_name in STABLE_LINE_SEARCH_FIELDS:
        if line_metadata and field_name not in line_metadata:
            continue
        domain = or_terms(field_name, terms)
        if not domain:
            continue
        ok = _run_line_query(
            erp,
            domain=[*base_domain, *domain],
            fields=line_fields,
            destination=candidates,
        )
        successful += int(ok)
        skipped += int(not ok)

    for field_name in STABLE_MOVE_SEARCH_FIELDS:
        if move_metadata and field_name not in move_metadata:
            continue
        domain = or_terms(f"move_id.{field_name}", terms)
        if not domain:
            continue
        ok = _run_line_query(
            erp,
            domain=[*base_domain, *domain],
            fields=line_fields,
            destination=candidates,
        )
        successful += int(ok)
        skipped += int(not ok)

    lines = sorted(
        candidates.values(),
        key=lambda row: (str(row.get("date") or ""), int(row.get("id") or 0)),
        reverse=True,
    )
    return CandidateLineResult(lines, successful, skipped)
