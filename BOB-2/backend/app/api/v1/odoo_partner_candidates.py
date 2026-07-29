"""Bounded partner-directory scoring for local multilingual Odoo searches."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from app.api.v1.odoo_search_helpers import value_text
from app.ml.name_matching.normalization import transliterate_arabic
from app.ml.name_matching.runtime import explain_similarity, get_local_name_matcher

logger = logging.getLogger(__name__)

MAX_PARTNERS_TO_SCORE = 5_000
MAX_SEARCH_TERMS = 8


@dataclass(frozen=True)
class PartnerCandidateResult:
    partner_ids: list[int]
    partner_texts: list[str]
    search_terms: list[str]
    rows_scored: int
    skipped_queries: int
    truncated: bool


def read_partner_directory(
    erp: Any,
    *,
    metadata: dict[str, dict[str, Any]],
    company_id: int | None,
) -> tuple[list[dict[str, Any]], int, bool]:
    domain: list[Any] = []
    if company_id and (not metadata or "company_id" in metadata):
        domain = [
            "|",
            ["company_id", "=", False],
            ["company_id", "=", int(company_id)],
        ]

    skipped = 0
    for fields in (["id", "name", "display_name", "ref"], ["id", "name"]):
        if metadata:
            fields = [field for field in fields if field in metadata]
        if "id" not in fields:
            fields.insert(0, "id")
        if "name" not in fields:
            fields.append("name")

        try:
            partners: list[dict[str, Any]] = []
            offset = 0
            while offset < MAX_PARTNERS_TO_SCORE:
                limit = min(500, MAX_PARTNERS_TO_SCORE - offset)
                batch = erp.execute_kw(
                    "res.partner",
                    "search_read",
                    [domain],
                    {
                        "fields": fields,
                        "order": "id asc",
                        "limit": limit,
                        "offset": offset,
                    },
                )
                if not batch:
                    break
                partners.extend(batch)
                offset += len(batch)
                if len(batch) < limit:
                    break
            return partners, skipped, len(partners) >= MAX_PARTNERS_TO_SCORE
        except Exception:
            skipped += 1
            logger.warning(
                "Partner directory read failed for fields=%s",
                fields,
                exc_info=True,
            )

    return [], skipped, False


def match_partner_directory(
    search_term: str,
    partners: list[dict[str, Any]],
) -> tuple[list[int], list[str]]:
    threshold = get_local_name_matcher().accept_threshold
    matched_ids: list[int] = []
    matched_texts: list[str] = []

    for partner in partners:
        partner_id = partner.get("id")
        if not isinstance(partner_id, int):
            continue

        best_score = 0.0
        best_text = ""
        for field_name in ("name", "display_name", "ref"):
            text = value_text(partner.get(field_name))
            if not text:
                continue
            score = explain_similarity(search_term, text).score
            if score > best_score:
                best_score = score
                best_text = text

        if best_score >= threshold:
            matched_ids.append(partner_id)
            if best_text:
                matched_texts.append(best_text)

    return matched_ids, matched_texts


def build_search_terms(search_term: str, matched_texts: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        cleaned = re.sub(r"\s+", " ", value or "").strip()
        key = cleaned.casefold()
        if len(cleaned) >= 2 and key not in seen:
            seen.add(key)
            ordered.append(cleaned)

    add(search_term)
    add(transliterate_arabic(search_term))

    for text in matched_texts:
        for token in re.findall(
            r"[A-Za-z\u0600-\u06FF][A-Za-z\u0600-\u06FF\-]*",
            text,
        ):
            if len(token) >= 3 and explain_similarity(search_term, token).decision == "match":
                add(token)
        if explain_similarity(search_term, text).decision == "match":
            add(text)
        if len(ordered) >= MAX_SEARCH_TERMS:
            break

    return ordered[:MAX_SEARCH_TERMS]


def discover_partner_candidates(
    erp: Any,
    *,
    search_term: str,
    metadata: dict[str, dict[str, Any]],
    company_id: int | None,
) -> PartnerCandidateResult:
    partners, skipped, truncated = read_partner_directory(
        erp,
        metadata=metadata,
        company_id=company_id,
    )
    partner_ids, partner_texts = match_partner_directory(search_term, partners)
    return PartnerCandidateResult(
        partner_ids=partner_ids,
        partner_texts=partner_texts,
        search_terms=build_search_terms(search_term, partner_texts),
        rows_scored=len(partners),
        skipped_queries=skipped,
        truncated=truncated,
    )
