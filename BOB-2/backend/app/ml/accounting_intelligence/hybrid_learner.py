"""Hybrid deep-semantic + structured-feature accounting learner.

Sentence-transformer embeddings provide the deep semantic signal. Structured
accounting features and chart-of-account candidate semantics are combined with
historical posted outcomes to produce explainable ranked recommendations.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from app.ml.accounting_intelligence.contracts import AccountingReferenceCatalog
from app.ml.accounting_intelligence.feature_engineering import (
    amount_bucket,
    infer_document_signals,
    lexical_account_score,
    normalize_accounting_text,
)
from app.services.accounting_ai import cosine


@dataclass(frozen=True)
class RetrievedLearningExample:
    source_reference: str
    text_preview: str
    vector: list[float]
    outputs: dict[str, Any]
    features: dict[str, Any]


class HybridAccountingLearner:
    """Ranks learned labels without possessing any ERP mutation capability."""

    def __init__(self, *, semantic_weight: float = 0.82, structured_weight: float = 0.18):
        total = semantic_weight + structured_weight
        if total <= 0:
            raise ValueError("Hybrid learner weights must have a positive total.")
        self.semantic_weight = semantic_weight / total
        self.structured_weight = structured_weight / total

    @staticmethod
    def _structured_similarity(query: dict[str, Any], example: dict[str, Any]) -> float:
        checks: list[float] = []
        for key in ("amount_bucket", "move_type", "currency"):
            q = query.get(key)
            e = example.get(key)
            if q and e and q != "unknown" and e != "unknown":
                checks.append(1.0 if str(q) == str(e) else 0.0)
        for key in (
            "vat_relevant",
            "bank_related",
            "payroll_related",
            "asset_related",
            "revenue_related",
            "expense_related",
        ):
            q = bool(query.get(key))
            e = bool(example.get(key))
            if q or e:
                checks.append(1.0 if q == e else 0.0)
        return sum(checks) / len(checks) if checks else 0.5

    def retrieve(
        self,
        *,
        query_vector: list[float],
        query_features: dict[str, Any],
        examples: Iterable[RetrievedLearningExample],
        top_k: int = 12,
    ) -> list[dict[str, Any]]:
        scored: list[dict[str, Any]] = []
        for example in examples:
            semantic = max(0.0, cosine(query_vector, example.vector))
            structured = self._structured_similarity(query_features, example.features)
            score = self.semantic_weight * semantic + self.structured_weight * structured
            if score < 0.20:
                continue
            scored.append(
                {
                    "source_reference": example.source_reference,
                    "score": round(score, 6),
                    "semantic_similarity": round(semantic, 6),
                    "structured_similarity": round(structured, 6),
                    "outputs": example.outputs,
                    "features": example.features,
                    "text_preview": example.text_preview[:500],
                }
            )
        scored.sort(key=lambda row: row["score"], reverse=True)
        return scored[: max(1, min(int(top_k), 50))]

    @staticmethod
    def _weighted_vote(retrieved: list[dict[str, Any]], output_key: str) -> list[tuple[int, float]]:
        """Return consensus confidence, separate from absolute evidence strength."""
        votes: dict[int, float] = defaultdict(float)
        total = 0.0
        for row in retrieved:
            weight = float(row["score"])
            raw = row["outputs"].get(output_key)
            values = raw if isinstance(raw, list) else [raw]
            clean_values: set[int] = set()
            for value in values:
                try:
                    if value is not None:
                        clean_values.add(int(value))
                except (TypeError, ValueError):
                    continue
            if not clean_values:
                continue
            per_value = weight / len(clean_values)
            for value in clean_values:
                votes[value] += per_value
            total += weight
        if total <= 0:
            return []
        ranked = [(identifier, min(1.0, score / total)) for identifier, score in votes.items()]
        ranked.sort(key=lambda item: item[1], reverse=True)
        return ranked

    @staticmethod
    def _catalog_map(rows: tuple[dict[str, Any], ...]) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        for row in rows:
            try:
                result[int(row["id"])] = dict(row)
            except (KeyError, TypeError, ValueError):
                continue
        return result

    def _account_candidates(
        self,
        *,
        query_text: str,
        votes: list[tuple[int, float]],
        catalog: AccountingReferenceCatalog,
        evidence_strength: float,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        account_map = self._catalog_map(catalog.accounts)
        candidates: list[dict[str, Any]] = []
        for account_id, consensus in votes[: max(limit * 2, 10)]:
            account = account_map.get(account_id)
            if account and bool(account.get("deprecated")):
                continue
            account = account or {"id": account_id}
            lexical = lexical_account_score(query_text, account) if account_map else 0.0
            learned_confidence = consensus * evidence_strength
            combined = min(0.995, learned_confidence * 0.92 + lexical * 0.08)
            candidates.append(
                {
                    "id": account_id,
                    "code": account.get("code"),
                    "name": account.get("name"),
                    "account_type": account.get("account_type"),
                    "confidence": round(combined, 4),
                    "historical_consensus": round(consensus, 4),
                    "evidence_strength": round(evidence_strength, 4),
                    "chart_semantic_score": round(lexical, 4),
                    "live_reference_resolved": account_id in account_map,
                }
            )
        candidates.sort(key=lambda item: item["confidence"], reverse=True)
        return candidates[:limit]

    @staticmethod
    def _finding(code: str, severity: str, message: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "code": code,
            "severity": severity,
            "message": message,
            "evidence": evidence or {},
        }

    def predict(
        self,
        *,
        query_text: str,
        query_vector: list[float],
        amount: float | None,
        move_type_hint: str | None,
        currency_hint: str | None,
        catalog: AccountingReferenceCatalog,
        examples: Iterable[RetrievedLearningExample],
        top_k: int = 12,
    ) -> dict[str, Any]:
        signals = infer_document_signals(query_text)
        query_features = {
            "amount_bucket": amount_bucket(amount),
            "move_type": move_type_hint or "unknown",
            "currency": currency_hint or "unknown",
            **signals,
        }
        retrieved = self.retrieve(
            query_vector=query_vector,
            query_features=query_features,
            examples=examples,
            top_k=top_k,
        )
        evidence_strength = max((float(row["score"]) for row in retrieved), default=0.0)

        debit_votes = self._weighted_vote(retrieved, "debit_account_ids")
        credit_votes = self._weighted_vote(retrieved, "credit_account_ids")
        journal_votes = self._weighted_vote(retrieved, "journal_id")
        partner_votes = self._weighted_vote(retrieved, "partner_id")
        tax_votes = self._weighted_vote(retrieved, "tax_ids")
        analytic_votes = self._weighted_vote(retrieved, "analytic_account_ids")

        debit_candidates = self._account_candidates(
            query_text=query_text,
            votes=debit_votes,
            catalog=catalog,
            evidence_strength=evidence_strength,
        )
        credit_candidates = self._account_candidates(
            query_text=query_text,
            votes=credit_votes,
            catalog=catalog,
            evidence_strength=evidence_strength,
        )

        journal_map = self._catalog_map(catalog.journals)
        partner_map = self._catalog_map(catalog.partners)
        tax_map = self._catalog_map(catalog.taxes)
        analytic_map = self._catalog_map(catalog.analytic_accounts)

        def enrich(
            votes: list[tuple[int, float]],
            mapping: dict[int, dict[str, Any]],
            fields: tuple[str, ...],
            limit: int = 5,
        ) -> list[dict[str, Any]]:
            items: list[dict[str, Any]] = []
            for identifier, consensus in votes[:limit]:
                row = mapping.get(identifier) or {}
                item = {
                    "id": identifier,
                    "confidence": round(consensus * evidence_strength, 4),
                    "historical_consensus": round(consensus, 4),
                    "evidence_strength": round(evidence_strength, 4),
                    "live_reference_resolved": identifier in mapping,
                }
                for field in fields:
                    item[field] = row.get(field)
                items.append(item)
            return items

        journal_candidates = enrich(journal_votes, journal_map, ("code", "name", "type"))
        partner_candidates = enrich(partner_votes, partner_map, ("name", "vat", "customer_rank", "supplier_rank"))
        tax_candidates = enrich(tax_votes, tax_map, ("name", "amount", "type_tax_use"))
        analytic_candidates = enrich(analytic_votes, analytic_map, ("code", "name"))

        strongest = 0.0
        for bucket in (debit_candidates, credit_candidates, journal_candidates):
            if bucket:
                strongest = max(strongest, float(bucket[0]["confidence"]))

        findings: list[dict[str, Any]] = []
        if not retrieved:
            findings.append(self._finding(
                "NO_HISTORICAL_EVIDENCE",
                "high",
                "No sufficiently similar posted accounting history was found; classification must remain unresolved.",
            ))
        if strongest < 0.60:
            findings.append(self._finding(
                "LOW_LEARNED_CONFIDENCE",
                "medium",
                "Learned confidence is below the accountant-review threshold.",
                {"confidence": round(strongest, 4), "threshold": 0.60},
            ))
        if not debit_candidates or not credit_candidates:
            findings.append(self._finding(
                "INCOMPLETE_DOUBLE_ENTRY_CLASSIFICATION",
                "high",
                "The learned evidence did not resolve both debit and credit sides.",
            ))
        if not journal_candidates:
            findings.append(self._finding(
                "JOURNAL_UNRESOLVED",
                "medium",
                "The target journal could not be resolved from learned posted history.",
            ))
        if debit_candidates and credit_candidates and debit_candidates[0]["id"] == credit_candidates[0]["id"]:
            findings.append(self._finding(
                "CONTRADICTORY_ACCOUNT_SIDES",
                "high",
                "Top learned debit and credit accounts are identical.",
                {"account_id": debit_candidates[0]["id"]},
            ))
        if query_features["vat_relevant"] and not tax_candidates:
            findings.append(self._finding(
                "VAT_SIGNAL_WITHOUT_TAX_RESOLUTION",
                "medium",
                "VAT/tax evidence is present but no historical tax candidate was resolved.",
            ))
        if amount is None:
            findings.append(self._finding(
                "AMOUNT_NOT_SUPPLIED",
                "info",
                "No explicit amount was supplied to the intelligence layer; amount-based similarity is unavailable.",
            ))
        elif abs(float(amount)) == 0:
            findings.append(self._finding(
                "ZERO_AMOUNT",
                "info",
                "The supplied accounting amount is zero and should be verified before entry preparation.",
            ))

        warnings = [finding["message"] for finding in findings if finding["severity"] in {"high", "medium"}]
        return {
            "query_features": query_features,
            "debit_accounts": debit_candidates,
            "credit_accounts": credit_candidates,
            "journals": journal_candidates,
            "partners": partner_candidates,
            "taxes": tax_candidates,
            "analytic_accounts": analytic_candidates,
            "retrieved_examples": retrieved,
            "evidence_strength": round(evidence_strength, 4),
            "confidence": round(strongest, 4),
            "audit_findings": findings,
            "warnings": warnings,
            "explainability": {
                "method": "deep semantic embedding + structured accounting similarity + weighted historical outcomes + chart candidate semantics",
                "semantic_weight": round(self.semantic_weight, 4),
                "structured_weight": round(self.structured_weight, 4),
                "confidence_calibration": "historical consensus multiplied by strongest retrieved evidence",
                "query_normalized": normalize_accounting_text(query_text)[:1000],
            },
            "audit_safe": {
                "auto_posted_to_erp": False,
                "approval_required": True,
                "erp_access_mode": "read_only_learning",
            },
        }
