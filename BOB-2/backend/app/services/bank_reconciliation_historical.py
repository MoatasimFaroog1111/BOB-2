"""Odoo history adapter and pure historical-consensus matcher."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from app.services.bank_reconciliation_contracts import SuggestionBatchContext
from app.services.bank_reconciliation_features import (
    amount_similarity,
    decimal_amount,
    detect_monetary_components,
    direction_similarity,
    is_tax_account_label,
    text_similarity,
    transaction_category,
    transaction_text,
)

_HISTORY_MIN_SCORE = 0.34
_HISTORY_TOP_K = 12
_REVIEW_THRESHOLD = 0.92


def _m2o(value: Any) -> tuple[int | None, str]:
    if isinstance(value, (list, tuple)) and value:
        try:
            identifier = int(value[0]) if value[0] else None
        except (TypeError, ValueError):
            identifier = None
        return identifier, str(value[1] if len(value) > 1 else "")
    if isinstance(value, int):
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
                        "counterparts": counterparts,
                    }
                )
        return historical


class HistoricalSuggestionMatcher:
    """Pure matcher using top-k evidence and weighted historical consensus."""

    def suggest(self, transaction: dict[str, Any], historical: list[dict[str, Any]]) -> dict[str, Any] | None:
        text = transaction_text(transaction)
        category = transaction_category(text)
        ranked: list[dict[str, Any]] = []

        for entry in historical:
            bank_text_score = text_similarity(text, str(entry.get("bank_text") or ""))
            amount_score = amount_similarity(transaction.get("amount"), entry.get("bank_amount"))
            category_score = (
                1.0
                if category != "general" and category == transaction_category(str(entry.get("bank_text") or ""))
                else 0.0
            )
            direction_score = direction_similarity(transaction.get("amount"), entry.get("bank_amount"))

            for counter in entry.get("counterparts") or []:
                account_id, account_label = _m2o(counter.get("account_id"))
                if not account_id:
                    continue
                counter_text_score = text_similarity(text, _counter_evidence_text(counter))
                text_score = max(bank_text_score, counter_text_score)
                if text_score < 0.12 and amount_score < 0.82:
                    continue
                score = min(
                    1.0,
                    text_score * 0.70
                    + amount_score * 0.12
                    + category_score * 0.10
                    + direction_score * 0.08,
                )
                if score < _HISTORY_MIN_SCORE:
                    continue

                bank_magnitude = abs(decimal_amount(entry.get("bank_amount")))
                line_magnitude = abs(_entry_amount(counter))
                share = (
                    float(min(Decimal("1.00"), line_magnitude / bank_magnitude)) if bank_magnitude else 1.0
                )
                partner_id, partner_label = _m2o(counter.get("partner_id"))
                analytic_id, analytic_label = _analytic_from_line(counter)
                ranked.append(
                    {
                        "score": score,
                        "weight": score * max(0.15, share),
                        "account_id": account_id,
                        "account_label": account_label,
                        "partner_id": partner_id,
                        "partner_label": partner_label,
                        "analytic_id": analytic_id,
                        "analytic_label": analytic_label,
                        "move_id": entry.get("move_id"),
                        "move_name": entry.get("move_name"),
                        "date": entry.get("date"),
                        "tax_like": is_tax_account_label(account_label),
                    }
                )

        if not ranked:
            return None
        ranked.sort(key=lambda item: (item["score"], item["weight"]), reverse=True)
        evidence = ranked[:_HISTORY_TOP_K]
        components = detect_monetary_components(transaction)
        prefer_non_tax = category == "bank_fees" and float(components.get("vat_amount") or 0) > 0

        account_votes: dict[int, float] = defaultdict(float)
        account_meta: dict[int, dict[str, Any]] = {}
        total_weight = 0.0
        for item in evidence:
            weight = float(item["weight"])
            if prefer_non_tax and item["tax_like"]:
                weight *= 0.20
            account_votes[int(item["account_id"])] += weight
            total_weight += weight
            account_meta.setdefault(int(item["account_id"]), item)
        if total_weight <= 0:
            return None

        ordered_accounts = sorted(account_votes.items(), key=lambda pair: pair[1], reverse=True)
        winning_account_id, winning_weight = ordered_accounts[0]
        winner = account_meta[winning_account_id]
        consensus = min(1.0, winning_weight / total_weight)
        winner_evidence = [item for item in evidence if int(item["account_id"]) == winning_account_id]
        strongest = max((float(item["score"]) for item in winner_evidence), default=0.0)
        confidence = min(0.985, strongest * (0.70 + 0.30 * consensus))

        partner_votes: dict[int, float] = defaultdict(float)
        partner_labels: dict[int, str] = {}
        analytic_votes: dict[int, float] = defaultdict(float)
        analytic_labels: dict[int, str] = {}
        for item in winner_evidence:
            weight = float(item["weight"])
            if item.get("partner_id"):
                partner_votes[int(item["partner_id"])] += weight
                partner_labels[int(item["partner_id"])] = str(item.get("partner_label") or "")
            if item.get("analytic_id"):
                analytic_votes[int(item["analytic_id"])] += weight
                analytic_labels[int(item["analytic_id"])] = str(item.get("analytic_label") or "")

        partner_id = max(partner_votes, key=partner_votes.get) if partner_votes else None
        analytic_id = max(analytic_votes, key=analytic_votes.get) if analytic_votes else None
        best_match = max(winner_evidence, key=lambda item: item["score"])
        alternatives = [
            {
                "account_id": account_id,
                "account_label": account_meta[account_id].get("account_label") or "",
                "historical_vote_share": round(vote / total_weight, 4),
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
            "confidence": round(confidence, 4),
            "source": "odoo_historical_consensus",
            "resolution_mode": "top_k_historical_consensus",
            "reason": (
                f"Top-k posted Odoo history selected account {winning_account_id} from "
                f"{len(winner_evidence)} supporting matches; historical consensus={consensus:.1%}, "
                f"strongest evidence={strongest:.1%}."
            ),
            "historical_move_id": best_match.get("move_id"),
            "historical_move_name": best_match.get("move_name"),
            "historical_date": best_match.get("date"),
            "historical_support_count": len(winner_evidence),
            "confidence_breakdown": {
                "historical_consensus": round(consensus, 4),
                "evidence_strength": round(strongest, 4),
            },
            "alternatives": alternatives,
            "needs_review": confidence < _REVIEW_THRESHOLD,
        }
