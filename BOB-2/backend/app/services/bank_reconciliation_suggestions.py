"""Hybrid, read-only suggestion engine for bank reconciliation.

Resolution order is intentionally deterministic and auditable:
1. Approved BOB Bank Rules.
2. Direct posted Odoo bank-history consensus.
3. Existing accounting-intelligence semantic memory for unresolved rows.

The service never posts to ERP. It only returns explainable candidates for accountant review.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from difflib import SequenceMatcher
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.services.accounting_intelligence import AccountingIntelligenceService
from app.services.bank_rules_engine import bank_rules_engine, transaction_statement_text
from app.services.bank_rules_service import bank_rules_service
from app.services.tenant_erp_service import tenant_erp_resolver


_MONEY = Decimal("0.01")
_REVIEW_THRESHOLD = 0.92
_HISTORY_MIN_SCORE = 0.34
_HISTORY_TOP_K = 12


@dataclass(frozen=True, slots=True)
class SuggestionBatchContext:
    organization_id: int
    company_id: int | None = None
    bank_journal_id: int | None = None
    bank_account_id: int | None = None
    history_limit: int = 600
    semantic_limit: int = 40


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(_MONEY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def _money_float(value: Decimal) -> float:
    return float(value.quantize(_MONEY, rounding=ROUND_HALF_UP))


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


def _normalize(text: Any) -> str:
    value = str(text or "").lower()
    value = value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي").replace("ة", "ه")
    value = re.sub(r"[\u064B-\u065F\u0670]", "", value)
    value = re.sub(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b", " ", value)
    value = re.sub(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b", " ", value)
    value = re.sub(
        r"\b(ref|reference|txn|transaction|date|time|sar|iban|swift|mada|visa|card|bank)\b",
        " ",
        value,
    )
    value = re.sub(r"[^\w\u0600-\u06FF]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tokens(text: Any) -> set[str]:
    return {token for token in _normalize(text).split() if len(token) > 2 and not token.isdigit()}


def _category(text: str) -> str:
    normalized = _normalize(text)
    # Fees must be detected before VAT because bank-fee descriptions commonly contain both.
    if re.search(r"رسوم|عموله|fee|charge|commission", normalized):
        return "bank_fees"
    if re.search(r"راتب|رواتب|salary|payroll|wps", normalized):
        return "payroll"
    if re.search(r"ضريبه|زكاه|زكاة|vat|tax", normalized):
        return "tax"
    if re.search(r"سداد|sadad|bill|فاتوره|فاتورة|mol|government", normalized):
        return "bill_payment"
    if re.search(r"تحويل|transfer|local transfer|instant payment", normalized):
        return "transfer"
    if re.search(r"pos|شبكه|مدي|مدى|card settlement|settlement", normalized):
        return "pos_settlement"
    return "general"


def _amount_similarity(left: Any, right: Any) -> float:
    a = abs(_decimal(left))
    b = abs(_decimal(right))
    if a == 0 or b == 0:
        return 0.0
    ratio = min(a, b) / max(a, b)
    if ratio >= Decimal("0.995"):
        return 1.0
    if ratio >= Decimal("0.98"):
        return 0.82
    if ratio >= Decimal("0.95"):
        return 0.65
    if ratio >= Decimal("0.90"):
        return 0.45
    return 0.0


def _text_similarity(left: str, right: str) -> float:
    a = _normalize(left)
    b = _normalize(right)
    if not a or not b:
        return 0.0
    sequence = SequenceMatcher(None, a, b).ratio()
    left_tokens = _tokens(a)
    right_tokens = _tokens(b)
    union = left_tokens | right_tokens
    overlap = len(left_tokens & right_tokens) / max(len(union), 1)
    containment = 0.0
    if left_tokens and right_tokens:
        containment = len(left_tokens & right_tokens) / max(min(len(left_tokens), len(right_tokens)), 1)
    return min(1.0, max(sequence, overlap, containment * 0.96))


def _entry_amount(line: dict[str, Any]) -> Decimal:
    balance = line.get("balance")
    if balance is not None:
        return _decimal(balance)
    return _decimal(line.get("debit")) - _decimal(line.get("credit"))


def _direction_similarity(left: Any, right: Any) -> float:
    a = _decimal(left)
    b = _decimal(right)
    if a == 0 or b == 0:
        return 0.0
    return 1.0 if (a > 0) == (b > 0) else 0.0


def _bank_line_text(line: dict[str, Any]) -> str:
    _move_id, move_name = _m2o(line.get("move_id"))
    _partner_id, partner_name = _m2o(line.get("partner_id"))
    return " ".join(
        filter(
            None,
            [str(line.get("name") or ""), str(line.get("ref") or ""), move_name, partner_name],
        )
    )


def _counter_evidence_text(line: dict[str, Any]) -> str:
    # Account label is deliberately excluded from similarity evidence. It is the target label,
    # so using it as an input would leak the answer into the matcher.
    _move_id, move_name = _m2o(line.get("move_id"))
    _partner_id, partner_name = _m2o(line.get("partner_id"))
    return " ".join(
        filter(
            None,
            [str(line.get("name") or ""), str(line.get("ref") or ""), move_name, partner_name],
        )
    )


def _transaction_text(transaction: dict[str, Any]) -> str:
    values = [
        transaction_statement_text(transaction),
        str(transaction.get("suggested_action_label") or ""),
        str(transaction.get("explanation") or ""),
        str(transaction.get("detected_category") or ""),
    ]
    return " ".join(value for value in values if value).strip()


def _is_tax_account_label(label: str) -> bool:
    normalized = _normalize(label)
    return bool(re.search(r"\bvat\b|input vat|vat input|value added tax|ضريبه|ضريبة|104041", normalized))


def _first_money(patterns: Iterable[re.Pattern[str]], text: str) -> Decimal:
    normalized = str(text or "").replace(",", " ")
    for pattern in patterns:
        match = pattern.search(normalized)
        if not match or not match.group(1):
            continue
        raw = re.sub(r"[^0-9.]", "", match.group(1))
        try:
            value = Decimal(raw).quantize(_MONEY, rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError):
            continue
        if value > 0:
            return value
    return Decimal("0.00")


def detect_monetary_components(transaction: dict[str, Any]) -> dict[str, Any]:
    """Extract bank-fee/VAT components without inventing a tax amount."""
    total = abs(_decimal(transaction.get("amount")))
    text = _transaction_text(transaction)
    if total <= 0:
        return {"gross_amount": 0.0, "fee_amount": 0.0, "vat_amount": 0.0, "vat_rate": None}

    fee = _first_money(
        (
            re.compile(r"\bFEE\s*0*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE),
            re.compile(r"\b(?:BANK\s*)?CHARGE\s*0*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE),
            re.compile(r"(?:رسوم|عموله|عمولة)\s*0*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE),
        ),
        text,
    )
    vat = _first_money(
        (
            re.compile(r"VAT\s*AMOUNT\s*0*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE),
            re.compile(r"(?:ضريبه|ضريبة)\s*(?:القيمه|القيمة)?\s*(?:المضافه|المضافة)?\s*0*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE),
        ),
        text,
    )
    if vat >= total:
        vat = Decimal("0.00")

    vat_rate: Decimal | None = None
    has_15_percent_signal = bool(
        re.search(r"VAT\s*%?\s*15|VAT%\s*15|15\s*%|ضريبه\s*القيمه\s*المضافه|الضريبة\s*القيمة\s*المضافة", text, re.IGNORECASE)
    )
    if has_15_percent_signal:
        vat_rate = Decimal("15.00")
        if vat <= 0:
            vat = (total * Decimal("15") / Decimal("115")).quantize(_MONEY, rounding=ROUND_HALF_UP)

    if fee > total:
        fee = Decimal("0.00")
    if fee <= 0 and vat > 0 and _category(text) == "bank_fees":
        fee = max(Decimal("0.00"), total - vat)

    reconciles = fee > 0 and vat >= 0 and abs((fee + vat) - total) <= Decimal("0.02")
    return {
        "gross_amount": _money_float(total),
        "fee_amount": _money_float(fee),
        "vat_amount": _money_float(vat),
        "vat_rate": _money_float(vat_rate) if vat_rate is not None else None,
        "components_reconcile_to_total": bool(reconciles),
    }


class OdooHistoricalBankEntryRepository:
    """Read adapter for posted Odoo bank history."""

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
        text = _transaction_text(transaction)
        category = _category(text)
        ranked: list[dict[str, Any]] = []

        for entry in historical:
            bank_text_score = _text_similarity(text, str(entry.get("bank_text") or ""))
            amount_score = _amount_similarity(transaction.get("amount"), entry.get("bank_amount"))
            category_score = 1.0 if category != "general" and category == _category(str(entry.get("bank_text") or "")) else 0.0
            direction_score = _direction_similarity(transaction.get("amount"), entry.get("bank_amount"))

            for counter in entry.get("counterparts") or []:
                account_id, account_label = _m2o(counter.get("account_id"))
                if not account_id:
                    continue
                counter_text_score = _text_similarity(text, _counter_evidence_text(counter))
                text_score = max(bank_text_score, counter_text_score)
                if text_score < 0.12 and amount_score < 0.82:
                    continue
                score = min(
                    1.0,
                    text_score * 0.70 + amount_score * 0.12 + category_score * 0.10 + direction_score * 0.08,
                )
                if score < _HISTORY_MIN_SCORE:
                    continue

                bank_magnitude = abs(_decimal(entry.get("bank_amount")))
                line_magnitude = abs(_entry_amount(counter))
                share = float(min(Decimal("1.00"), line_magnitude / bank_magnitude)) if bank_magnitude else 1.0
                # Preserve smaller split lines as evidence while preventing a VAT line from
                # outranking the primary expense solely because it belongs to the same move.
                line_weight = max(0.15, share)
                partner_id, partner_label = _m2o(counter.get("partner_id"))
                analytic_id, analytic_label = _analytic_from_line(counter)
                ranked.append(
                    {
                        "score": score,
                        "weight": score * line_weight,
                        "account_id": account_id,
                        "account_label": account_label,
                        "partner_id": partner_id,
                        "partner_label": partner_label,
                        "analytic_id": analytic_id,
                        "analytic_label": analytic_label,
                        "move_id": entry.get("move_id"),
                        "move_name": entry.get("move_name"),
                        "date": entry.get("date"),
                        "tax_like": _is_tax_account_label(account_label),
                    }
                )

        if not ranked:
            return None
        ranked.sort(key=lambda item: (item["score"], item["weight"]), reverse=True)
        evidence = ranked[:_HISTORY_TOP_K]

        # When explicit VAT is embedded in a bank-fee transaction, the primary suggestion
        # should be the non-tax fee/expense line. VAT remains available as a detected split.
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

        # Resolve partner/analytic from evidence supporting the winning account only.
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
        alternatives = []
        for account_id, vote in ordered_accounts[:3]:
            meta = account_meta[account_id]
            alternatives.append(
                {
                    "account_id": account_id,
                    "account_label": meta.get("account_label") or "",
                    "historical_vote_share": round(vote / total_weight, 4),
                }
            )

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


class SemanticMemoryAdvisor:
    """Adapter over the existing learned accounting memory."""

    def __init__(self, db: Session, organization_id: int):
        self._service = AccountingIntelligenceService(db)
        self._organization_id = organization_id

    @staticmethod
    def _candidate_bucket(prediction: dict[str, Any], amount: Any) -> list[dict[str, Any]]:
        value = _decimal(amount)
        if value < 0:
            return list(prediction.get("debit_accounts") or [])
        if value > 0:
            return list(prediction.get("credit_accounts") or [])
        candidates = list(prediction.get("debit_accounts") or []) + list(prediction.get("credit_accounts") or [])
        candidates.sort(key=lambda item: float(item.get("confidence") or 0), reverse=True)
        return candidates

    def suggest(
        self,
        transaction: dict[str, Any],
        *,
        company_id: int | None,
        bank_account_id: int | None,
    ) -> dict[str, Any] | None:
        text = _transaction_text(transaction)
        if len(text.strip()) < 4:
            return None
        prediction = self._service.predict(
            organization_id=self._organization_id,
            text=text,
            amount=float(_decimal(transaction.get("amount"))),
            move_type_hint="entry",
            currency_hint="SAR",
            top_k=12,
            company_id=company_id,
        )
        candidates = [
            item
            for item in self._candidate_bucket(prediction, transaction.get("amount"))
            if int(item.get("id") or 0) > 0 and (not bank_account_id or int(item.get("id") or 0) != int(bank_account_id))
        ]
        if not candidates:
            return None
        candidate = candidates[0]
        confidence = float(candidate.get("confidence") or 0.0)
        partner = next(iter(prediction.get("partners") or []), {})
        analytic = next(iter(prediction.get("analytic_accounts") or []), {})
        return {
            "suggested_account_id": int(candidate["id"]),
            "suggested_account_label": " ".join(
                str(part) for part in (candidate.get("code"), candidate.get("name")) if part
            ).strip(),
            "suggested_partner_id": int(partner.get("id") or 0) or None,
            "suggested_partner_label": str(partner.get("name") or ""),
            "suggested_analytic_account_id": int(analytic.get("id") or 0) or None,
            "suggested_analytic_account_label": " ".join(
                str(part) for part in (analytic.get("code"), analytic.get("name")) if part
            ).strip(),
            "confidence": round(confidence, 4),
            "source": "accounting_intelligence_memory",
            "resolution_mode": "semantic_structured_learning",
            "reason": (
                "Existing accounting-intelligence memory selected the counterpart account using semantic embeddings, "
                "structured accounting features, historical outcomes, and live chart semantics."
            ),
            "confidence_breakdown": {
                "semantic_structured_confidence": round(confidence, 4),
                "evidence_strength": float(prediction.get("evidence_strength") or 0.0),
                "historical_consensus": float(candidate.get("historical_consensus") or 0.0),
            },
            "alternatives": [
                {
                    "account_id": int(item.get("id") or 0),
                    "account_label": " ".join(
                        str(part) for part in (item.get("code"), item.get("name")) if part
                    ).strip(),
                    "confidence": float(item.get("confidence") or 0.0),
                }
                for item in candidates[:3]
            ],
            "audit_findings": prediction.get("audit_findings") or [],
            "needs_review": confidence < _REVIEW_THRESHOLD,
        }


def _merge_nonempty(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    result = dict(primary)
    for key in (
        "suggested_partner_id",
        "suggested_partner_label",
        "suggested_analytic_account_id",
        "suggested_analytic_account_label",
    ):
        if not result.get(key) and secondary.get(key):
            result[key] = secondary[key]
    return result


def combine_advisors(
    historical: dict[str, Any] | None,
    semantic: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if historical is None:
        return semantic
    if semantic is None:
        return historical

    historical_account = int(historical.get("suggested_account_id") or 0)
    semantic_account = int(semantic.get("suggested_account_id") or 0)
    historical_confidence = float(historical.get("confidence") or 0.0)
    semantic_confidence = float(semantic.get("confidence") or 0.0)

    if historical_account and historical_account == semantic_account:
        winner = _merge_nonempty(historical, semantic)
        combined = min(0.99, max(historical_confidence, semantic_confidence) + 0.20 * min(historical_confidence, semantic_confidence))
        winner.update(
            {
                "confidence": round(combined, 4),
                "source": "historical_semantic_consensus",
                "resolution_mode": "ensemble_agreement",
                "reason": (
                    "Direct posted bank-history consensus and semantic accounting memory independently selected the same "
                    f"counterpart account {historical_account}."
                ),
                "advisor_agreement": True,
                "needs_review": combined < _REVIEW_THRESHOLD,
            }
        )
        winner["confidence_breakdown"] = {
            "historical": round(historical_confidence, 4),
            "semantic": round(semantic_confidence, 4),
        }
        return winner

    historical_wins = historical_confidence >= semantic_confidence
    winner = dict(historical if historical_wins else semantic)
    loser = semantic if historical_wins else historical
    margin = abs(historical_confidence - semantic_confidence)
    winner.update(
        {
            "advisor_agreement": False,
            "advisor_conflict": {
                "historical_account_id": historical_account or None,
                "historical_confidence": round(historical_confidence, 4),
                "semantic_account_id": semantic_account or None,
                "semantic_confidence": round(semantic_confidence, 4),
                "confidence_margin": round(margin, 4),
            },
            "needs_review": True,
            "reason": (
                f"Historical and semantic advisors disagreed. The higher-confidence {winner.get('source')} candidate is "
                "shown for review; automatic acceptance is blocked."
            ),
        }
    )
    winner = _merge_nonempty(winner, loser)
    return winner


class BankReconciliationSuggestionService:
    """Application orchestrator. No posting capability is exposed by this service."""

    def __init__(
        self,
        db: Session,
        context: SuggestionBatchContext,
        *,
        history_repository: OdooHistoricalBankEntryRepository | None = None,
        matcher: HistoricalSuggestionMatcher | None = None,
    ):
        self.db = db
        self.context = context
        self.history_repository = history_repository or OdooHistoricalBankEntryRepository()
        self.matcher = matcher or HistoricalSuggestionMatcher()

    @staticmethod
    def _base(transaction: dict[str, Any]) -> dict[str, Any]:
        return {
            "row_number": transaction.get("row_number"),
            "date": str(transaction.get("date") or ""),
            "description": str(transaction.get("description") or ""),
            "amount": float(_decimal(transaction.get("amount"))),
            "detected_components": detect_monetary_components(transaction),
            "safe_to_post": False,
        }

    def suggest(self, transactions: list[dict[str, Any]]) -> dict[str, Any]:
        if not transactions:
            return {
                "status": "success",
                "items": [],
                "history_count": 0,
                "confident_count": 0,
                "method": "bob_rule_then_historical_then_semantic_v2",
                "safe_to_post": False,
            }

        _connection, erp = tenant_erp_resolver.resolve(self.db, self.context.organization_id)
        historical = self.history_repository.fetch(erp, self.context)
        active_rules: list[dict[str, Any]] = []
        if self.context.bank_journal_id:
            active_rules = bank_rules_service.active_rules(
                self.db,
                organization_id=self.context.organization_id,
                journal_id=int(self.context.bank_journal_id),
                company_id=self.context.company_id,
            )

        staged: list[tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]] = []
        semantic_candidates: list[int] = []
        for index, transaction in enumerate(transactions):
            base = self._base(transaction)
            rule_resolution = bank_rules_engine.resolve(transaction, active_rules) if active_rules else None
            if rule_resolution is not None:
                staged.append((base, rule_resolution, None))
                continue

            historical_resolution = self.matcher.suggest(transaction, historical)
            staged.append((base, historical_resolution, None))
            if (
                historical_resolution is None
                or float(historical_resolution.get("confidence") or 0.0) < _REVIEW_THRESHOLD
            ):
                semantic_candidates.append(index)

        semantic_budget = max(0, min(int(self.context.semantic_limit or 0), len(semantic_candidates), 100))
        semantic_errors = 0
        if semantic_budget:
            advisor = SemanticMemoryAdvisor(self.db, self.context.organization_id)
            for index in semantic_candidates[:semantic_budget]:
                transaction = transactions[index]
                try:
                    semantic_resolution = advisor.suggest(
                        transaction,
                        company_id=self.context.company_id,
                        bank_account_id=self.context.bank_account_id,
                    )
                except Exception:
                    semantic_errors += 1
                    semantic_resolution = None
                base, historical_resolution, _unused = staged[index]
                staged[index] = (base, historical_resolution, semantic_resolution)

        items: list[dict[str, Any]] = []
        for base, first_resolution, semantic_resolution in staged:
            # Approved rule resolutions are final in the precedence chain, including
            # ambiguous same-priority results which intentionally block weaker advisors.
            if first_resolution and str(first_resolution.get("source") or "") == "bob_bank_rule":
                resolution = dict(first_resolution)
            else:
                resolution = combine_advisors(first_resolution, semantic_resolution)

            if resolution is None:
                resolution = {
                    "confidence": 0.0,
                    "source": "unresolved",
                    "resolution_mode": "manual_review_required",
                    "reason": "No approved BOB rule or sufficiently strong historical/semantic evidence resolved this row.",
                    "needs_review": True,
                }
            items.append({**base, **resolution})

        confident = len(
            [
                item
                for item in items
                if item.get("suggested_account_id")
                and not item.get("needs_review")
                and not item.get("advisor_conflict")
            ]
        )
        return {
            "status": "success",
            "items": items,
            "history_count": len(historical),
            "active_bank_rule_count": len(active_rules),
            "semantic_attempted_count": semantic_budget,
            "semantic_error_count": semantic_errors,
            "confident_count": confident,
            "method": "bob_rule_then_historical_then_semantic_v2",
            "safe_to_post": False,
            "note": (
                "Approved BOB Bank Rules have deterministic priority. Remaining rows use top-k posted Odoo history and, "
                "within a bounded budget, the existing semantic accounting-learning memory. Conflicting advisors are always flagged for review."
            ),
        }
