"""Phase 4 bank-reconciliation accuracy strategy.

V4 is an additive strategy around the proven V3 historical matcher.  It keeps V3 VAT
and analytic inference intact, then hardens the two remaining weak points measured on
the untouched production benchmark:

* counterparty identity resolution, preferring the posted counterpart partner as the
  accounting label while using the bank-line partner/narration only as identity evidence;
* account candidate generation across the whole eligible historical corpus instead of
  only reranking the nearest Top-K rows.

The module is pure/read-only.  It receives already-posted historical entries, filters
future evidence as-of the transaction date, and has no ERP mutation capability.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from app.services.bank_reconciliation_features import (
    amount_similarity,
    decimal_amount,
    direction_similarity,
    is_tax_account_label,
    normalize_text,
    text_similarity,
    transaction_category,
    transaction_text,
)
from app.services.bank_reconciliation_historical import (
    HistoricalSuggestionMatcher,
    counterparty_fingerprint,
    fingerprint_similarity,
)

_ENGINE_VERSION = "v4_identity_candidate_calibration"
_REVIEW_THRESHOLD = 0.97
_MAX_ACCOUNT_CANDIDATES = 7


def _m2o(value: Any) -> tuple[int | None, str]:
    if value is None or value is False or value == "":
        return None, ""
    if isinstance(value, (list, tuple)) and value:
        try:
            identifier = int(value[0]) if value[0] else None
        except (TypeError, ValueError):
            identifier = None
        return identifier, str(value[1] if len(value) > 1 else "")
    if isinstance(value, int) and not isinstance(value, bool):
        return value, ""
    return None, ""


def _entry_amount(line: dict[str, Any]) -> Decimal:
    if line.get("balance") is not None:
        return decimal_amount(line.get("balance"))
    return decimal_amount(line.get("debit")) - decimal_amount(line.get("credit"))


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except (TypeError, ValueError):
        return None


def _eligible_history(transaction: dict[str, Any], historical: list[dict[str, Any]]) -> list[dict[str, Any]]:
    target = _parse_date(transaction.get("date"))
    if target is None:
        return list(historical)
    result: list[dict[str, Any]] = []
    for entry in historical:
        observed = _parse_date(entry.get("date"))
        if observed is not None and observed > target:
            continue
        result.append(entry)
    return result


def _recency_score(transaction_date: Any, historical_date: Any) -> float:
    target = _parse_date(transaction_date)
    observed = _parse_date(historical_date)
    if target is None or observed is None:
        return 0.75
    delta = (target - observed).days
    if delta < 0:
        return 0.0
    if delta <= 30:
        return 1.0
    if delta <= 90:
        return 0.96
    if delta <= 180:
        return 0.90
    if delta <= 365:
        return 0.82
    return 0.70


def _primary_counterpart(entry: dict[str, Any]) -> dict[str, Any] | None:
    ranked: list[tuple[bool, Decimal, dict[str, Any]]] = []
    for line in entry.get("counterparts") or []:
        account_id, account_label = _m2o(line.get("account_id"))
        if not account_id:
            continue
        magnitude = abs(_entry_amount(line))
        if magnitude <= 0:
            continue
        ranked.append((is_tax_account_label(account_label), magnitude, line))
    if not ranked:
        return None
    non_tax = [item for item in ranked if not item[0]]
    pool = non_tax or ranked
    pool.sort(key=lambda item: item[1], reverse=True)
    return pool[0][2]


def _accounting_partner(entry: dict[str, Any]) -> tuple[int | None, str, str]:
    """Return the partner label used by accounting, then bank-line partner as fallback.

    This order intentionally differs from V3.  The production untouched benchmark labels
    the posted counterpart partner first; the bank-line partner is valuable identity
    evidence but must not silently override the accounting counterpart.
    """
    primary = _primary_counterpart(entry)
    if primary is not None:
        partner_id, partner_label = _m2o(primary.get("partner_id"))
        if partner_id:
            return partner_id, partner_label, "counterpart_line"
    raw_id = entry.get("bank_partner_id")
    try:
        bank_partner_id = int(raw_id) if raw_id else None
    except (TypeError, ValueError):
        bank_partner_id = None
    if bank_partner_id:
        return bank_partner_id, str(entry.get("bank_partner_label") or ""), "bank_line"
    return None, "", ""


def _identity_partner_label(entry: dict[str, Any]) -> str:
    labels: list[str] = []
    bank_label = str(entry.get("bank_partner_label") or "").strip()
    if bank_label:
        labels.append(bank_label)
    primary = _primary_counterpart(entry)
    if primary is not None:
        _partner_id, partner_label = _m2o(primary.get("partner_id"))
        if partner_label:
            labels.append(partner_label)
    return " ".join(dict.fromkeys(labels))


def _canonical_alnum(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def identity_keys(text: Any) -> tuple[str, ...]:
    """Extract stable beneficiary identifiers without treating one-off references as truth.

    Keys are only useful when they repeat in historical evidence.  IBANs receive a
    dedicated prefix; long numeric account-like values receive another prefix.  Short
    transaction references and generated Odoo move numbers are intentionally ignored.
    """
    raw = str(text or "").upper()
    keys: list[str] = []
    for match in re.finditer(r"(?<![A-Z0-9])([A-Z]{2}\s*\d{2}(?:\s*[A-Z0-9]){10,30})(?![A-Z0-9])", raw):
        compact = _canonical_alnum(match.group(1))
        if 14 <= len(compact) <= 34:
            keys.append(f"iban:{compact}")
    for match in re.finditer(r"(?<!\d)(\d{8,24})(?!\d)", raw):
        digits = match.group(1)
        if len(set(digits)) == 1:
            continue
        keys.append(f"acct:{digits}")
    return tuple(dict.fromkeys(keys))


def _identity_overlap(query_keys: set[str], entry_keys: set[str]) -> tuple[int, int]:
    overlap = query_keys & entry_keys
    iban = sum(1 for item in overlap if item.startswith("iban:"))
    account = sum(1 for item in overlap if item.startswith("acct:"))
    return iban, account


def _amount_band(value: Any) -> int:
    amount = abs(float(decimal_amount(value)))
    if amount <= 0:
        return 0
    # Half-decade logarithmic bands keep SAR 5k near SAR 6k without merging SAR 500.
    return int(math.floor(math.log10(max(amount, 0.01)) * 2.0))


def _entry_category(entry: dict[str, Any]) -> str:
    return transaction_category(str(entry.get("bank_text") or ""))


def _partner_identity_evidence(
    transaction: dict[str, Any],
    entry: dict[str, Any],
) -> dict[str, float | int]:
    query_text = transaction_text(transaction)
    bank_text = str(entry.get("bank_text") or "")
    partner_label = _identity_partner_label(entry)
    query_keys = set(identity_keys(query_text))
    entry_keys = set(identity_keys(bank_text))
    iban_overlap, account_overlap = _identity_overlap(query_keys, entry_keys)
    fingerprint = fingerprint_similarity(query_text, bank_text)
    text_score = text_similarity(query_text, bank_text)
    label_score = text_similarity(query_text, partner_label) if partner_label else 0.0
    amount_score = amount_similarity(transaction.get("amount"), entry.get("bank_amount"))
    direction_score = direction_similarity(transaction.get("amount"), entry.get("bank_amount"))
    category = transaction_category(query_text)
    category_score = 1.0 if category != "general" and category == _entry_category(entry) else 0.0
    recency = _recency_score(transaction.get("date"), entry.get("date"))
    exact_bonus = min(0.50, iban_overlap * 0.50 + account_overlap * 0.22)
    score = min(
        1.35,
        fingerprint * 0.30
        + text_score * 0.18
        + label_score * 0.20
        + amount_score * 0.06
        + direction_score * 0.05
        + category_score * 0.07
        + recency * 0.04
        + exact_bonus,
    )
    return {
        "score": score,
        "fingerprint": fingerprint,
        "text": text_score,
        "label": label_score,
        "amount": amount_score,
        "direction": direction_score,
        "category": category_score,
        "recency": recency,
        "iban_overlap": iban_overlap,
        "account_overlap": account_overlap,
    }


class PartnerIdentityResolverV4:
    """Resolve partner from identity clusters and abstain only on genuine ambiguity."""

    def resolve(
        self,
        transaction: dict[str, Any],
        historical: list[dict[str, Any]],
    ) -> dict[str, Any]:
        votes: dict[int, float] = defaultdict(float)
        labels: dict[int, str] = {}
        strongest: dict[int, float] = defaultdict(float)
        support: dict[int, int] = defaultdict(int)
        exact_support: dict[int, int] = defaultdict(int)
        bank_alias_support: dict[int, int] = defaultdict(int)

        for entry in historical:
            partner_id, partner_label, source = _accounting_partner(entry)
            if not partner_id:
                continue
            evidence = _partner_identity_evidence(transaction, entry)
            score = float(evidence["score"])
            fingerprint = float(evidence["fingerprint"])
            label_score = float(evidence["label"])
            exact = int(evidence["iban_overlap"]) + int(evidence["account_overlap"])
            if score < 0.33 and fingerprint < 0.30 and label_score < 0.45 and not exact:
                continue
            weight = score * (0.86 + 0.14 * float(evidence["recency"]))
            if source == "counterpart_line":
                weight *= 1.12
            if int(evidence["iban_overlap"]):
                weight *= 1.65
            elif int(evidence["account_overlap"]):
                weight *= 1.30
            if fingerprint >= 0.82:
                weight *= 1.20
            elif fingerprint >= 0.65:
                weight *= 1.08
            votes[partner_id] += weight
            labels[partner_id] = partner_label
            strongest[partner_id] = max(strongest[partner_id], score)
            support[partner_id] += 1
            exact_support[partner_id] += exact
            if entry.get("bank_partner_id") and int(entry.get("bank_partner_id")) == partner_id:
                bank_alias_support[partner_id] += 1

        if not votes:
            return {
                "partner_id": None,
                "partner_label": "",
                "confidence": 0.0,
                "vote_share": 0.0,
                "margin": 0.0,
                "support": 0,
                "exact_support": 0,
                "ambiguous": True,
                "method": "identity_cluster_v3",
            }

        ordered = sorted(votes.items(), key=lambda pair: pair[1], reverse=True)
        candidate, candidate_weight = ordered[0]
        second_weight = ordered[1][1] if len(ordered) > 1 else 0.0
        total = sum(votes.values())
        share = candidate_weight / total if total else 0.0
        margin = (candidate_weight - second_weight) / total if total else 0.0
        candidate_support = support[candidate]
        candidate_exact = exact_support[candidate]
        candidate_strongest = strongest[candidate]
        alias_support = bank_alias_support[candidate]

        confidence = min(
            0.995,
            candidate_strongest * 0.42
            + share * 0.32
            + max(0.0, margin) * 0.12
            + min(candidate_support, 5) / 5.0 * 0.08
            + min(candidate_exact, 2) / 2.0 * 0.04
            + min(alias_support, 2) / 2.0 * 0.02,
        )
        decisive_exact = candidate_exact >= 1 and share >= 0.52 and margin >= 0.08
        decisive_cluster = (
            share >= 0.58
            and margin >= 0.12
            and candidate_support >= 2
            and candidate_strongest >= 0.64
        )
        decisive_single = share >= 0.72 and candidate_strongest >= 0.82
        resolved = decisive_exact or decisive_cluster or decisive_single

        return {
            "partner_id": candidate if resolved else None,
            "partner_label": labels.get(candidate, "") if resolved else "",
            "candidate_partner_id": candidate,
            "candidate_partner_label": labels.get(candidate, ""),
            "confidence": round(confidence, 4),
            "vote_share": round(share, 4),
            "margin": round(max(0.0, margin), 4),
            "support": candidate_support,
            "exact_support": candidate_exact,
            "bank_alias_support": alias_support,
            "ambiguous": not resolved,
            "method": "identity_cluster_v3",
        }


class AccountCandidateGeneratorV4:
    """Generate/rank account candidates from full historical conditional evidence."""

    def rank(
        self,
        transaction: dict[str, Any],
        historical: list[dict[str, Any]],
        partner_resolution: dict[str, Any],
        *,
        baseline: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        query_text = transaction_text(transaction)
        query_category = transaction_category(query_text)
        query_band = _amount_band(transaction.get("amount"))
        resolved_partner = partner_resolution.get("partner_id")

        partner_account_counts: dict[int, int] = defaultdict(int)
        partner_total = 0
        category_account_counts: dict[int, int] = defaultdict(int)
        category_total = 0
        direction_account_counts: dict[int, int] = defaultdict(int)
        direction_total = 0
        account_votes: dict[int, float] = defaultdict(float)
        account_best: dict[int, float] = defaultdict(float)
        account_support: dict[int, int] = defaultdict(int)
        account_exact_support: dict[int, int] = defaultdict(int)
        account_labels: dict[int, str] = {}
        account_partner_support: dict[int, int] = defaultdict(int)
        account_band_support: dict[int, int] = defaultdict(int)

        # First pass builds conditional priors from the whole eligible corpus.
        for entry in historical:
            primary = _primary_counterpart(entry)
            if primary is None:
                continue
            account_id, account_label = _m2o(primary.get("account_id"))
            if not account_id:
                continue
            account_labels[account_id] = account_label
            entry_partner, _partner_label, _source = _accounting_partner(entry)
            if resolved_partner and entry_partner == resolved_partner:
                partner_account_counts[account_id] += 1
                partner_total += 1
            if query_category != "general" and _entry_category(entry) == query_category:
                category_account_counts[account_id] += 1
                category_total += 1
            if direction_similarity(transaction.get("amount"), entry.get("bank_amount")) >= 1.0:
                direction_account_counts[account_id] += 1
                direction_total += 1

        query_keys = set(identity_keys(query_text))
        for entry in historical:
            primary = _primary_counterpart(entry)
            if primary is None:
                continue
            account_id, account_label = _m2o(primary.get("account_id"))
            if not account_id:
                continue
            bank_text = str(entry.get("bank_text") or "")
            fingerprint = fingerprint_similarity(query_text, bank_text)
            text_score = text_similarity(query_text, bank_text)
            amount_score = amount_similarity(transaction.get("amount"), entry.get("bank_amount"))
            direction_score = direction_similarity(transaction.get("amount"), entry.get("bank_amount"))
            recency = _recency_score(transaction.get("date"), entry.get("date"))
            category_match = query_category != "general" and _entry_category(entry) == query_category
            entry_partner, _partner_label, _source = _accounting_partner(entry)
            entry_keys = set(identity_keys(bank_text))
            iban_overlap, account_overlap = _identity_overlap(query_keys, entry_keys)
            exact_identity = iban_overlap + account_overlap
            partner_match = bool(resolved_partner and entry_partner == resolved_partner)
            band_match = abs(_amount_band(entry.get("bank_amount")) - query_band) <= 1

            # Candidate recall gate: identity, partner, semantic narration, category+direction,
            # or very close amount may all introduce a candidate.  This deliberately avoids
            # limiting generation to the nearest Top-K rows.
            if not (
                exact_identity
                or partner_match
                or fingerprint >= 0.28
                or text_score >= 0.34
                or (category_match and direction_score >= 1.0)
                or amount_score >= 0.94
            ):
                continue

            score = (
                fingerprint * 0.24
                + text_score * 0.15
                + amount_score * 0.07
                + direction_score * 0.05
                + recency * 0.06
                + (0.10 if category_match else 0.0)
                + (0.27 if partner_match else 0.0)
                + min(0.40, iban_overlap * 0.40 + account_overlap * 0.18)
            )
            if band_match:
                score += 0.04
            score = min(1.45, score)
            weight = score * (0.88 + 0.12 * recency)
            account_votes[account_id] += weight
            account_best[account_id] = max(account_best[account_id], score)
            account_support[account_id] += 1
            account_exact_support[account_id] += exact_identity
            if partner_match:
                account_partner_support[account_id] += 1
            if band_match:
                account_band_support[account_id] += 1
            account_labels[account_id] = account_label

        # Preserve V3 candidates in the union even when V4 evidence is sparse.
        if baseline:
            baseline_ids: list[int] = []
            try:
                primary = int(baseline.get("suggested_account_id") or 0)
            except (TypeError, ValueError):
                primary = 0
            if primary:
                baseline_ids.append(primary)
                account_labels.setdefault(primary, str(baseline.get("suggested_account_label") or ""))
            for item in baseline.get("alternatives") or []:
                try:
                    identifier = int(item.get("account_id") or 0)
                except (TypeError, ValueError):
                    continue
                if identifier:
                    baseline_ids.append(identifier)
                    account_labels.setdefault(identifier, str(item.get("account_label") or ""))
            for rank, identifier in enumerate(dict.fromkeys(baseline_ids)):
                account_votes[identifier] += max(0.08, 0.24 - rank * 0.05)
                account_best[identifier] = max(account_best[identifier], 0.45 - rank * 0.05)

        if not account_votes:
            return []

        max_vote = max(account_votes.values()) or 1.0
        candidates: list[dict[str, Any]] = []
        for account_id, raw_vote in account_votes.items():
            vote_strength = raw_vote / max_vote
            partner_probability = (
                partner_account_counts[account_id] / partner_total if partner_total else 0.0
            )
            category_probability = (
                category_account_counts[account_id] / category_total if category_total else 0.0
            )
            direction_probability = (
                direction_account_counts[account_id] / direction_total if direction_total else 0.0
            )
            support_bonus = min(1.0, account_support[account_id] / 5.0)
            exact_bonus = min(1.0, account_exact_support[account_id] / 2.0)
            partner_support = min(1.0, account_partner_support[account_id] / 3.0)
            band_support = min(1.0, account_band_support[account_id] / 3.0)

            final_score = (
                vote_strength * 0.36
                + account_best[account_id] * 0.20
                + partner_probability * 0.20
                + category_probability * 0.08
                + direction_probability * 0.04
                + support_bonus * 0.04
                + exact_bonus * 0.05
                + partner_support * 0.02
                + band_support * 0.01
            )
            candidates.append(
                {
                    "account_id": account_id,
                    "account_label": account_labels.get(account_id, ""),
                    "score": round(final_score, 6),
                    "raw_vote": round(raw_vote, 6),
                    "best_evidence": round(account_best[account_id], 4),
                    "historical_support": account_support[account_id],
                    "partner_probability": round(partner_probability, 4),
                    "category_probability": round(category_probability, 4),
                    "direction_probability": round(direction_probability, 4),
                    "exact_identity_support": account_exact_support[account_id],
                    "partner_aligned_support": account_partner_support[account_id],
                    "amount_band_support": account_band_support[account_id],
                }
            )

        candidates.sort(
            key=lambda item: (
                float(item["score"]),
                int(item["exact_identity_support"]),
                int(item["partner_aligned_support"]),
                int(item["historical_support"]),
            ),
            reverse=True,
        )
        return candidates[:_MAX_ACCOUNT_CANDIDATES]


class HistoricalSuggestionMatcherV4:
    """Decorator strategy that protects V3 VAT/analytic behavior and improves identity/account."""

    def __init__(
        self,
        *,
        baseline_matcher: HistoricalSuggestionMatcher | None = None,
        partner_resolver: PartnerIdentityResolverV4 | None = None,
        candidate_generator: AccountCandidateGeneratorV4 | None = None,
    ) -> None:
        self.baseline_matcher = baseline_matcher or HistoricalSuggestionMatcher()
        self.partner_resolver = partner_resolver or PartnerIdentityResolverV4()
        self.candidate_generator = candidate_generator or AccountCandidateGeneratorV4()

    def suggest(self, transaction: dict[str, Any], historical: list[dict[str, Any]]) -> dict[str, Any] | None:
        eligible = _eligible_history(transaction, historical)
        baseline = self.baseline_matcher.suggest(transaction, eligible)
        if baseline is None:
            return None

        partner = self.partner_resolver.resolve(transaction, eligible)
        candidates = self.candidate_generator.rank(
            transaction,
            eligible,
            partner,
            baseline=baseline,
        )
        if not candidates:
            result = dict(baseline)
            result["engine_version"] = _ENGINE_VERSION
            result["resolution_mode"] = "v4_baseline_fallback"
            result["partner_resolution"] = partner
            return result

        winner = candidates[0]
        total_score = sum(max(0.0, float(item["score"])) for item in candidates) or 1.0
        winner_share = float(winner["score"]) / total_score
        second_score = float(candidates[1]["score"]) if len(candidates) > 1 else 0.0
        margin = max(0.0, (float(winner["score"]) - second_score) / max(float(winner["score"]), 1e-9))
        evidence_strength = min(1.0, float(winner["best_evidence"]))
        partner_confidence = float(partner.get("confidence") or 0.0)
        exact_support = min(1.0, int(winner["exact_identity_support"]) / 2.0)
        aligned_support = min(1.0, int(winner["partner_aligned_support"]) / 3.0)

        confidence = min(
            0.995,
            evidence_strength * 0.34
            + min(1.0, winner_share * 2.5) * 0.20
            + margin * 0.17
            + partner_confidence * 0.15
            + exact_support * 0.08
            + aligned_support * 0.06,
        )
        # Do not inflate confidence merely because V4 changed the rank; retain the
        # proven baseline confidence when it is lower than the V4 evidence envelope.
        baseline_confidence = float(baseline.get("confidence") or 0.0)
        if int(baseline.get("suggested_account_id") or 0) == int(winner["account_id"]):
            confidence = min(0.995, max(confidence, baseline_confidence * 0.98))

        result = dict(baseline)
        result.update(
            {
                "suggested_account_id": int(winner["account_id"]),
                "suggested_account_label": str(winner.get("account_label") or ""),
                "suggested_partner_id": partner.get("partner_id"),
                "suggested_partner_label": str(partner.get("partner_label") or ""),
                "confidence": round(confidence, 4),
                # Backward-compatible public source; engine_version is additive.
                "source": "odoo_historical_consensus",
                "engine_version": _ENGINE_VERSION,
                "resolution_mode": "identity_conditioned_candidate_generator_v4",
                "needs_review": confidence < _REVIEW_THRESHOLD or bool(partner.get("ambiguous")),
                "safe_to_post": False,
                "partner_resolution": partner,
                "candidate_generator": {
                    "candidate_count": len(candidates),
                    "winner_share": round(winner_share, 4),
                    "winner_margin": round(margin, 4),
                    "full_history_candidate_generation": True,
                    "uses_future_history": False,
                },
                "confidence_breakdown": {
                    **(baseline.get("confidence_breakdown") or {}),
                    "v4_evidence_strength": round(evidence_strength, 4),
                    "v4_candidate_share": round(winner_share, 4),
                    "v4_candidate_margin": round(margin, 4),
                    "v4_partner_confidence": round(partner_confidence, 4),
                    "v4_exact_identity_support": int(winner["exact_identity_support"]),
                    "v4_partner_aligned_support": int(winner["partner_aligned_support"]),
                },
            }
        )
        result["alternatives"] = [
            {
                "account_id": int(item["account_id"]),
                "account_label": str(item.get("account_label") or ""),
                "historical_vote_share": round(float(item["score"]) / total_score, 4),
                "partner_aligned_support": int(item["partner_aligned_support"]),
                "exact_identity_support": int(item["exact_identity_support"]),
                "category_probability": float(item["category_probability"]),
            }
            for item in candidates[:3]
        ]
        result["reason"] = (
            f"V4 identity-conditioned historical candidates selected account {winner['account_id']}; "
            f"candidate margin={margin:.1%}, partner={'resolved' if partner.get('partner_id') else 'ambiguous'}, "
            f"partner confidence={partner_confidence:.1%}. VAT/analytic inference remains V3-protected."
        )
        return result


__all__ = [
    "AccountCandidateGeneratorV4",
    "HistoricalSuggestionMatcherV4",
    "PartnerIdentityResolverV4",
    "identity_keys",
]
