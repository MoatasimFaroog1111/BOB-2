"""Odoo history adapter and leakage-safe historical intelligence for bank reconciliation.

The module deliberately remains framework-free at the matching layer.  It learns only
from posted Odoo history passed by the caller and never mutates ERP state.

V3 hardening adds:
- as-of filtering so future posted rows cannot influence an older transaction;
- counterparty fingerprints for noisy bank narrations;
- partner recovery from both bank and counterpart lines;
- partner-aware account reranking over the historical Top-K candidates;
- historical VAT propensity inference instead of relying on explicit ``VAT`` text;
- calibrated evidence diagnostics while keeping every result review-only.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from app.services.bank_reconciliation_contracts import SuggestionBatchContext
from app.services.bank_reconciliation_features import (
    amount_similarity,
    decimal_amount,
    detect_monetary_components,
    direction_similarity,
    is_tax_account_label,
    normalize_text,
    text_similarity,
    transaction_category,
    transaction_text,
)

_HISTORY_MIN_SCORE = 0.30
_HISTORY_TOP_K = 30
_VAT_TOP_K = 24
_REVIEW_THRESHOLD = 0.95

_NOISE_TOKENS = {
    "bank",
    "riyadh",
    "riyad",
    "payment",
    "payments",
    "instant",
    "transfer",
    "local",
    "outgoing",
    "incoming",
    "sarie",
    "ips",
    "beneficiary",
    "beneficiaryname",
    "beneficiaryaccount",
    "account",
    "iban",
    "reference",
    "ref",
    "transaction",
    "txn",
    "mada",
    "visa",
    "card",
    "sar",
    "amount",
    "fee",
    "fees",
    "charge",
    "charges",
    "vat",
    "tax",
    "تحويل",
    "محلي",
    "فوري",
    "حواله",
    "حوالة",
    "رسوم",
    "ضريبه",
    "ضريبة",
    "القيمه",
    "القيمة",
    "المضافه",
    "المضافة",
    "مرجع",
    "بنك",
}


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


def _analytic_from_line(line: dict[str, Any]) -> tuple[int | None, str]:
    analytic_id, analytic_label = _m2o(line.get("analytic_account_id"))
    if analytic_id:
        return analytic_id, analytic_label
    distribution = line.get("analytic_distribution")
    if isinstance(distribution, dict) and distribution:
        first_key = next(iter(distribution.keys()), None)
        if first_key:
            try:
                return int(str(first_key).split(",")[0]), ""
            except (TypeError, ValueError):
                return None, ""
    return None, ""


def _available_fields(erp: Any, model: str, desired: list[str]) -> set[str]:
    try:
        data = erp.execute_kw(model, "fields_get", [desired], {"attributes": ["type", "string"]})
        return set(data.keys()) if isinstance(data, dict) else set()
    except Exception:
        return set()


def _entry_amount(line: dict[str, Any]):
    balance = line.get("balance")
    if balance is not None:
        return decimal_amount(balance)
    return decimal_amount(line.get("debit")) - decimal_amount(line.get("credit"))


def _bank_line_text(line: dict[str, Any]) -> str:
    _move_id, move_name = _m2o(line.get("move_id"))
    _partner_id, partner_name = _m2o(line.get("partner_id"))
    return " ".join(
        filter(None, [str(line.get("name") or ""), str(line.get("ref") or ""), move_name, partner_name])
    )


def _counter_evidence_text(line: dict[str, Any]) -> str:
    # The target account label is deliberately excluded to prevent target leakage.
    _move_id, move_name = _m2o(line.get("move_id"))
    _partner_id, partner_name = _m2o(line.get("partner_id"))
    return " ".join(
        filter(None, [str(line.get("name") or ""), str(line.get("ref") or ""), move_name, partner_name])
    )


def counterparty_fingerprint(text: Any) -> tuple[str, ...]:
    """Return stable counterparty-like tokens while removing bank boilerplate and refs."""
    tokens: list[str] = []
    for token in normalize_text(text).split():
        if token in _NOISE_TOKENS or len(token) < 3 or token.isdigit():
            continue
        if re.fullmatch(r"[a-z0-9]{12,}", token):
            continue
        if sum(ch.isdigit() for ch in token) >= max(4, len(token) // 2):
            continue
        tokens.append(token)
    # Preserve narration order while deduplicating aliases repeated in the same row.
    return tuple(dict.fromkeys(tokens))


def fingerprint_similarity(left: Any, right: Any) -> float:
    a = set(counterparty_fingerprint(left))
    b = set(counterparty_fingerprint(right))
    if not a or not b:
        return 0.0
    overlap = len(a & b)
    if not overlap:
        return 0.0
    jaccard = overlap / len(a | b)
    containment = overlap / min(len(a), len(b))
    return min(1.0, max(jaccard, containment * 0.97))


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except (TypeError, ValueError):
        return None


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
        return 0.95
    if delta <= 180:
        return 0.90
    if delta <= 365:
        return 0.82
    return 0.72


def _entry_has_vat(entry: dict[str, Any]) -> bool:
    for line in entry.get("counterparts") or []:
        _account_id, account_label = _m2o(line.get("account_id"))
        if is_tax_account_label(account_label):
            return True
    return False


def _entry_vat_ratio(entry: dict[str, Any]) -> float | None:
    gross = abs(decimal_amount(entry.get("bank_amount")))
    if gross <= 0:
        return None
    vat = Decimal("0.00")
    for line in entry.get("counterparts") or []:
        _account_id, account_label = _m2o(line.get("account_id"))
        if is_tax_account_label(account_label):
            vat += abs(_entry_amount(line))
    if vat <= 0 or vat >= gross:
        return None
    return float(vat / gross)


def _primary_counterpart(entry: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[tuple[Decimal, bool, dict[str, Any]]] = []
    for line in entry.get("counterparts") or []:
        account_id, account_label = _m2o(line.get("account_id"))
        if not account_id:
            continue
        magnitude = abs(_entry_amount(line))
        if magnitude <= 0:
            continue
        candidates.append((magnitude, is_tax_account_label(account_label), line))
    if not candidates:
        return None
    non_tax = [item for item in candidates if not item[1]]
    pool = non_tax or candidates
    pool.sort(key=lambda item: item[0], reverse=True)
    return pool[0][2]


def _entry_primary_account_id(entry: dict[str, Any]) -> int | None:
    primary = _primary_counterpart(entry)
    if primary is None:
        return None
    identifier, _label = _m2o(primary.get("account_id"))
    return identifier


def _entry_partner(entry: dict[str, Any]) -> tuple[int | None, str, str]:
    bank_partner_id = entry.get("bank_partner_id")
    bank_partner_label = str(entry.get("bank_partner_label") or "")
    try:
        normalized_bank_partner = int(bank_partner_id) if bank_partner_id else None
    except (TypeError, ValueError):
        normalized_bank_partner = None
    if normalized_bank_partner:
        return normalized_bank_partner, bank_partner_label, "bank_line"

    primary = _primary_counterpart(entry)
    if primary is not None:
        partner_id, partner_label = _m2o(primary.get("partner_id"))
        if partner_id:
            return partner_id, partner_label, "counterpart_line"
    return None, "", ""


class OdooHistoricalBankEntryRepository:
    """Read-only adapter for posted Odoo bank history."""

    def fetch(self, erp: Any, context: SuggestionBatchContext) -> list[dict[str, Any]]:
        domain: list[Any] = [["parent_state", "=", "posted"]]
        if context.company_id:
            domain.append(["company_id", "=", int(context.company_id)])
        if context.bank_journal_id:
            domain.append(["journal_id", "=", int(context.bank_journal_id)])
        if context.bank_account_id:
            domain.append(["account_id", "=", int(context.bank_account_id)])

        base_fields = [
            "id",
            "date",
            "name",
            "ref",
            "move_id",
            "account_id",
            "partner_id",
            "debit",
            "credit",
            "balance",
            "journal_id",
        ]
        analytic_fields = sorted(
            _available_fields(erp, "account.move.line", ["analytic_account_id", "analytic_distribution"])
        )
        line_fields = base_fields + [field for field in analytic_fields if field not in base_fields]
        limit = max(50, min(int(context.history_limit or 600), 1500))

        bank_lines = erp.execute_kw(
            "account.move.line",
            "search_read",
            [domain],
            {"fields": base_fields, "order": "date desc, id desc", "limit": limit},
        )
        if not bank_lines and context.bank_journal_id:
            fallback_domain: list[Any] = [
                ["parent_state", "=", "posted"],
                ["journal_id", "=", int(context.bank_journal_id)],
            ]
            if context.company_id:
                fallback_domain.append(["company_id", "=", int(context.company_id)])
            bank_lines = erp.execute_kw(
                "account.move.line",
                "search_read",
                [fallback_domain],
                {"fields": base_fields, "order": "date desc, id desc", "limit": limit},
            )

        move_ids = sorted(
            {move_id for move_id, _name in (_m2o(line.get("move_id")) for line in bank_lines) if move_id}
        )
        if not move_ids:
            return []

        try:
            all_lines = erp.execute_kw(
                "account.move.line",
                "search_read",
                [[["move_id", "in", move_ids], ["parent_state", "=", "posted"]]],
                {"fields": line_fields, "order": "date desc, id asc", "limit": min(len(move_ids) * 10, 8000)},
            )
        except Exception as exc:
            if "analytic" not in str(exc).lower():
                raise
            all_lines = erp.execute_kw(
                "account.move.line",
                "search_read",
                [[["move_id", "in", move_ids], ["parent_state", "=", "posted"]]],
                {"fields": base_fields, "order": "date desc, id asc", "limit": min(len(move_ids) * 10, 8000)},
            )

        by_move: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for line in all_lines:
            move_id, _name = _m2o(line.get("move_id"))
            if move_id:
                by_move[move_id].append(line)

        historical: list[dict[str, Any]] = []
        for bank_line in bank_lines:
            move_id, move_name = _m2o(bank_line.get("move_id"))
            if not move_id:
                continue
            bank_account_id, _bank_account_name = _m2o(bank_line.get("account_id"))
            bank_partner_id, bank_partner_label = _m2o(bank_line.get("partner_id"))
            counterparts: list[dict[str, Any]] = []
            for line in by_move.get(move_id, []):
                account_id, _account_name = _m2o(line.get("account_id"))
                if context.bank_account_id and account_id == int(context.bank_account_id):
                    continue
                if not context.bank_account_id and account_id == bank_account_id:
                    continue
                if abs(_entry_amount(line)) == 0:
                    continue
                counterparts.append(line)
            if counterparts:
                historical.append(
                    {
                        "move_id": move_id,
                        "move_name": move_name,
                        "date": bank_line.get("date") or "",
                        "bank_text": _bank_line_text(bank_line),
                        "bank_amount": _entry_amount(bank_line),
                        "bank_partner_id": bank_partner_id,
                        "bank_partner_label": bank_partner_label,
                        "counterparts": counterparts,
                    }
                )
        return historical


class HistoricalSuggestionMatcher:
    """Pure V3 matcher using counterparty-aware Top-K historical evidence."""

    def _eligible_history(
        self,
        transaction: dict[str, Any],
        historical: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        target_date = _parse_date(transaction.get("date"))
        if target_date is None:
            return historical
        eligible: list[dict[str, Any]] = []
        for entry in historical:
            observed = _parse_date(entry.get("date"))
            if observed is not None and observed > target_date:
                continue
            eligible.append(entry)
        return eligible

    def _vat_inference(
        self,
        transaction: dict[str, Any],
        category: str,
        entry_evidence: list[dict[str, Any]],
        historical: list[dict[str, Any]],
        *,
        winning_account_id: int,
        partner_id: int | None,
    ) -> dict[str, Any]:
        explicit = detect_monetary_components(transaction)
        explicit_vat = float(explicit.get("vat_amount") or 0.0)
        if explicit_vat > 0:
            return {
                "present": True,
                "confidence": 0.995,
                "propensity": 1.0,
                "historical_support": 0,
                "historical_positive": 0,
                "amount": explicit_vat,
                "rate": explicit.get("vat_rate"),
                "method": "explicit_statement_component",
                "advisory_only": True,
            }

        top_entries = entry_evidence[:_VAT_TOP_K]
        local_total = sum(float(item["entry_weight"]) for item in top_entries)
        local_positive = sum(
            float(item["entry_weight"])
            for item in top_entries
            if bool(item["vat_present"])
        )
        local_propensity = local_positive / local_total if local_total > 0 else 0.0
        local_positive_count = sum(1 for item in top_entries if item["vat_present"])

        account_rows = [
            entry for entry in historical if _entry_primary_account_id(entry) == winning_account_id
        ]
        account_propensity = (
            sum(1 for entry in account_rows if _entry_has_vat(entry)) / len(account_rows)
            if account_rows
            else None
        )

        partner_rows: list[dict[str, Any]] = []
        if partner_id:
            for entry in historical:
                entry_partner_id, _label, _source = _entry_partner(entry)
                if entry_partner_id == partner_id:
                    partner_rows.append(entry)
        partner_propensity = (
            sum(1 for entry in partner_rows if _entry_has_vat(entry)) / len(partner_rows)
            if partner_rows
            else None
        )

        weighted_parts: list[tuple[float, float]] = []
        if top_entries:
            weighted_parts.append((local_propensity, 0.55))
        if account_propensity is not None and len(account_rows) >= 2:
            weighted_parts.append((account_propensity, 0.25))
        if partner_propensity is not None and len(partner_rows) >= 2:
            weighted_parts.append((partner_propensity, 0.20))
        denominator = sum(weight for _value, weight in weighted_parts)
        propensity = (
            sum(value * weight for value, weight in weighted_parts) / denominator
            if denominator
            else 0.0
        )

        strongest = float(top_entries[0]["entry_score"]) if top_entries else 0.0
        strongest_is_vat = bool(top_entries and top_entries[0]["vat_present"])
        threshold = 0.46 if category == "bank_fees" else 0.60
        sufficient_positive_support = local_positive_count >= 2 or (
            strongest >= 0.88 and strongest_is_vat
        )
        present = bool(propensity >= threshold and sufficient_positive_support)

        distance = abs(propensity - threshold)
        confidence = min(0.98, 0.55 + distance * 0.70)
        if not top_entries:
            confidence = 0.50

        inferred_amount: float | None = None
        inferred_rate: float | None = None
        if present and category == "bank_fees":
            ratios = [
                (float(item["entry_weight"]), item.get("vat_ratio"))
                for item in top_entries
                if item.get("vat_ratio") is not None and item["vat_present"]
            ]
            ratio_weight = sum(weight for weight, _ratio in ratios)
            if ratio_weight > 0:
                average_ratio = sum(weight * float(ratio) for weight, ratio in ratios) / ratio_weight
                gross = abs(float(decimal_amount(transaction.get("amount"))))
                if 0 < average_ratio < 0.50 and gross > 0:
                    inferred_amount = round(gross * average_ratio, 2)
                    if 0.12 <= average_ratio <= 0.14:
                        inferred_rate = 15.0

        return {
            "present": present,
            "confidence": round(confidence, 4),
            "propensity": round(propensity, 4),
            "historical_support": len(top_entries),
            "historical_positive": local_positive_count,
            "account_propensity": round(account_propensity, 4) if account_propensity is not None else None,
            "partner_propensity": round(partner_propensity, 4) if partner_propensity is not None else None,
            "amount": inferred_amount,
            "rate": inferred_rate,
            "method": "historical_vat_propensity_v2",
            "advisory_only": True,
        }

    def suggest(self, transaction: dict[str, Any], historical: list[dict[str, Any]]) -> dict[str, Any] | None:
        text = transaction_text(transaction)
        category = transaction_category(text)
        eligible_history = self._eligible_history(transaction, historical)
        ranked: list[dict[str, Any]] = []
        entry_evidence_by_move: dict[int, dict[str, Any]] = {}

        for entry in eligible_history:
            bank_text = str(entry.get("bank_text") or "")
            bank_text_score = text_similarity(text, bank_text)
            fingerprint_score = fingerprint_similarity(text, bank_text)
            amount_score = amount_similarity(transaction.get("amount"), entry.get("bank_amount"))
            category_score = (
                1.0
                if category != "general" and category == transaction_category(bank_text)
                else 0.0
            )
            direction_score = direction_similarity(transaction.get("amount"), entry.get("bank_amount"))
            recency_score = _recency_score(transaction.get("date"), entry.get("date"))
            if recency_score <= 0:
                continue

            entry_score = min(
                1.0,
                bank_text_score * 0.50
                + fingerprint_score * 0.20
                + amount_score * 0.08
                + category_score * 0.08
                + direction_score * 0.06
                + recency_score * 0.08,
            )
            move_id = int(entry.get("move_id") or 0)
            entry_weight = entry_score * (0.85 + 0.15 * recency_score)
            if move_id:
                entry_evidence_by_move[move_id] = {
                    "move_id": move_id,
                    "entry_score": entry_score,
                    "entry_weight": entry_weight,
                    "fingerprint_score": fingerprint_score,
                    "vat_present": _entry_has_vat(entry),
                    "vat_ratio": _entry_vat_ratio(entry),
                    "date": entry.get("date"),
                }

            entry_partner_id, entry_partner_label, entry_partner_source = _entry_partner(entry)
            has_non_tax_counterpart = any(
                not is_tax_account_label(_m2o(line.get("account_id"))[1])
                for line in entry.get("counterparts") or []
                if _m2o(line.get("account_id"))[0]
            )

            for counter in entry.get("counterparts") or []:
                account_id, account_label = _m2o(counter.get("account_id"))
                if not account_id:
                    continue
                counter_text_score = text_similarity(text, _counter_evidence_text(counter))
                text_score = max(bank_text_score, counter_text_score)
                if text_score < 0.10 and fingerprint_score < 0.20 and amount_score < 0.82:
                    continue
                score = min(
                    1.0,
                    text_score * 0.50
                    + fingerprint_score * 0.20
                    + amount_score * 0.08
                    + category_score * 0.08
                    + direction_score * 0.06
                    + recency_score * 0.08,
                )
                if score < _HISTORY_MIN_SCORE:
                    continue

                bank_magnitude = abs(decimal_amount(entry.get("bank_amount")))
                line_magnitude = abs(_entry_amount(counter))
                share = (
                    float(min(Decimal("1.00"), line_magnitude / bank_magnitude)) if bank_magnitude else 1.0
                )
                counter_partner_id, counter_partner_label = _m2o(counter.get("partner_id"))
                partner_id = counter_partner_id or entry_partner_id
                partner_label = counter_partner_label or entry_partner_label
                partner_source = "counterpart_line" if counter_partner_id else entry_partner_source
                analytic_id, analytic_label = _analytic_from_line(counter)
                tax_like = is_tax_account_label(account_label)
                base_weight = score * max(0.15, share) * (0.90 + 0.10 * recency_score)
                ranked.append(
                    {
                        "score": score,
                        "weight": base_weight,
                        "fingerprint_score": fingerprint_score,
                        "account_id": account_id,
                        "account_label": account_label,
                        "partner_id": partner_id,
                        "partner_label": partner_label,
                        "partner_source": partner_source,
                        "analytic_id": analytic_id,
                        "analytic_label": analytic_label,
                        "move_id": move_id,
                        "move_name": entry.get("move_name"),
                        "date": entry.get("date"),
                        "tax_like": tax_like,
                        "entry_has_non_tax": has_non_tax_counterpart,
                    }
                )

        if not ranked:
            return None
        ranked.sort(key=lambda item: (item["score"], item["weight"]), reverse=True)
        evidence = ranked[:_HISTORY_TOP_K]
        entry_evidence = sorted(
            entry_evidence_by_move.values(),
            key=lambda item: (item["entry_score"], item["entry_weight"]),
            reverse=True,
        )

        # Resolve the counterparty before the account winner.  This lets repeated
        # employee/vendor patterns rerank a correct Top-3 account above a generic
        # payable/receivable candidate without hard-coding any chart-of-account ID.
        partner_votes: dict[int, float] = defaultdict(float)
        partner_labels: dict[int, str] = {}
        partner_support_counts: dict[int, int] = defaultdict(int)
        partner_strongest: dict[int, float] = defaultdict(float)
        for item in evidence:
            if item["tax_like"] or not item.get("partner_id"):
                continue
            identifier = int(item["partner_id"])
            weight = float(item["weight"]) * (1.0 + 0.35 * float(item["fingerprint_score"]))
            if item.get("partner_source") == "bank_line":
                weight *= 1.10
            partner_votes[identifier] += weight
            partner_support_counts[identifier] += 1
            partner_strongest[identifier] = max(partner_strongest[identifier], float(item["score"]))
            partner_labels[identifier] = str(item.get("partner_label") or "")

        partner_id: int | None = None
        partner_confidence = 0.0
        if partner_votes:
            total_partner_weight = sum(partner_votes.values())
            candidate_partner = max(partner_votes, key=partner_votes.get)
            candidate_share = partner_votes[candidate_partner] / total_partner_weight if total_partner_weight else 0.0
            candidate_strongest = partner_strongest[candidate_partner]
            candidate_support = partner_support_counts[candidate_partner]
            if candidate_share >= 0.42 or candidate_strongest >= 0.78 or candidate_support >= 2:
                partner_id = candidate_partner
                partner_confidence = min(
                    0.99,
                    candidate_strongest * 0.55 + candidate_share * 0.35 + min(candidate_support, 4) / 4 * 0.10,
                )

        components = detect_monetary_components(transaction)
        prefer_non_tax = category == "bank_fees" and float(components.get("vat_amount") or 0) > 0

        account_votes: dict[int, float] = defaultdict(float)
        account_meta: dict[int, dict[str, Any]] = {}
        account_partner_support: dict[int, int] = defaultdict(int)
        total_weight = 0.0
        for item in evidence:
            weight = float(item["weight"])
            if item["tax_like"] and item["entry_has_non_tax"]:
                weight *= 0.06
            elif prefer_non_tax and item["tax_like"]:
                weight *= 0.20

            if partner_id:
                if item.get("partner_id") == partner_id:
                    weight *= 1.45
                    account_partner_support[int(item["account_id"])] += 1
                elif item.get("partner_id"):
                    weight *= 0.72
                else:
                    weight *= 0.94

            fingerprint_score = float(item["fingerprint_score"])
            if fingerprint_score >= 0.80:
                weight *= 1.12
            elif fingerprint_score >= 0.60:
                weight *= 1.05

            account_votes[int(item["account_id"])] += weight
            total_weight += weight
            current_meta = account_meta.get(int(item["account_id"]))
            if current_meta is None or float(item["score"]) > float(current_meta["score"]):
                account_meta[int(item["account_id"])] = item
        if total_weight <= 0:
            return None

        ordered_accounts = sorted(account_votes.items(), key=lambda pair: pair[1], reverse=True)
        winning_account_id, winning_weight = ordered_accounts[0]
        winner = account_meta[winning_account_id]
        consensus = min(1.0, winning_weight / total_weight)
        second_weight = ordered_accounts[1][1] if len(ordered_accounts) > 1 else 0.0
        margin = max(0.0, (winning_weight - second_weight) / total_weight)
        winner_evidence = [item for item in evidence if int(item["account_id"]) == winning_account_id]
        strongest = max((float(item["score"]) for item in winner_evidence), default=0.0)
        support_factor = min(1.0, len(winner_evidence) / 3.0)
        partner_alignment = (
            min(1.0, account_partner_support[winning_account_id] / max(len(winner_evidence), 1))
            if partner_id
            else 0.0
        )
        confidence = min(
            0.995,
            strongest * 0.48
            + consensus * 0.24
            + margin * 0.14
            + support_factor * 0.08
            + partner_confidence * 0.04
            + partner_alignment * 0.02,
        )

        # If the globally resolved partner had weak evidence, restrict the final
        # partner vote to evidence supporting the selected account.  Conversely,
        # retain a strong bank-line partner even when the counterpart line is empty.
        winner_partner_votes: dict[int, float] = defaultdict(float)
        winner_partner_labels: dict[int, str] = {}
        analytic_votes: dict[int, float] = defaultdict(float)
        analytic_labels: dict[int, str] = {}
        for item in winner_evidence:
            weight = float(item["weight"])
            if item.get("partner_id"):
                identifier = int(item["partner_id"])
                winner_partner_votes[identifier] += weight
                winner_partner_labels[identifier] = str(item.get("partner_label") or "")
            if item.get("analytic_id"):
                identifier = int(item["analytic_id"])
                analytic_votes[identifier] += weight
                analytic_labels[identifier] = str(item.get("analytic_label") or "")

        if partner_id is None and winner_partner_votes:
            partner_id = max(winner_partner_votes, key=winner_partner_votes.get)
            partner_labels[partner_id] = winner_partner_labels.get(partner_id, "")
        analytic_id = max(analytic_votes, key=analytic_votes.get) if analytic_votes else None
        best_match = max(winner_evidence, key=lambda item: item["score"])

        vat_inference = self._vat_inference(
            transaction,
            category,
            entry_evidence,
            eligible_history,
            winning_account_id=winning_account_id,
            partner_id=partner_id,
        )

        alternatives = [
            {
                "account_id": account_id,
                "account_label": account_meta[account_id].get("account_label") or "",
                "historical_vote_share": round(vote / total_weight, 4),
                "partner_aligned_support": account_partner_support.get(account_id, 0),
            }
            for account_id, vote in ordered_accounts[:3]
        ]

        return {
            "suggested_account_id": winning_account_id,
            "suggested_account_label": str(winner.get("account_label") or ""),
            "suggested_partner_id": partner_id,
            "suggested_partner_label": partner_labels.get(partner_id, "") if partner_id else "",
            "suggested_analytic_account_id": analytic_id,
            "suggested_analytic_account_label": analytic_labels.get(analytic_id, "") if analytic_id else "",
            "predicted_vat_present": bool(vat_inference["present"]),
            "vat_inference": vat_inference,
            "confidence": round(confidence, 4),
            "source": "odoo_historical_consensus",
            "engine_version": "v3_partner_vat_reranker",
            "resolution_mode": "partner_aware_top_k_reranker",
            "reason": (
                f"Partner-aware posted Odoo history selected account {winning_account_id}; "
                f"consensus={consensus:.1%}, margin={margin:.1%}, strongest evidence={strongest:.1%}, "
                f"partner={'resolved' if partner_id else 'unresolved'}, VAT propensity={float(vat_inference['propensity']):.1%}."
            ),
            "historical_move_id": best_match.get("move_id"),
            "historical_move_name": best_match.get("move_name"),
            "historical_date": best_match.get("date"),
            "historical_support_count": len(winner_evidence),
            "confidence_breakdown": {
                "historical_consensus": round(consensus, 4),
                "candidate_margin": round(margin, 4),
                "evidence_strength": round(strongest, 4),
                "partner_confidence": round(partner_confidence, 4),
                "partner_alignment": round(partner_alignment, 4),
            },
            "alternatives": alternatives,
            "needs_review": confidence < _REVIEW_THRESHOLD,
            "safe_to_post": False,
        }
