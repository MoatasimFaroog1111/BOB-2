from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

SOURCE_TYPES = {
    "invoice",
    "receipt",
    "payment_voucher",
    "purchase_order",
    "bank_statement",
    "journal_entry",
    "trial_balance",
    "vendor_bill",
    "ocr_text",
    "manual_text",
}

ARABIC_NUMERIC_TRANSLATION = str.maketrans("٠١٢٣٤٥٦٧٨٩٬", "0123456789,")


@dataclass
class AgentFinding:
    agent: str
    role: str
    confidence: float
    summary: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "role": self.role,
            "confidence": round(self.confidence, 4),
            "summary": self.summary,
            "details": self.details,
        }


class AccountingMultiAgentOrchestrator:
    """Lightweight GMAWS-style workflow adapted for BOB accounting flows.

    The uploaded GMAWS project is a general multi-agent framework with robot-design
    dependencies. This class keeps the useful workflow concept while avoiding heavy
    robotics packages such as pybullet/trimesh/numpy pins inside the accounting app.
    """

    def run(
        self,
        *,
        text: str,
        source_type: str = "manual_text",
        organization_id: int = 1,
        language: Literal["auto", "ar", "en"] = "auto",
    ) -> dict[str, Any]:
        clean_text = text.strip()
        if len(clean_text) < 8:
            raise ValueError("Text is too short for multi-agent accounting analysis.")
        if source_type not in SOURCE_TYPES:
            raise ValueError(f"Unsupported source_type: {source_type}")

        extracted = self._extract_financial_signals(clean_text)
        findings = [
            self._intake_agent(clean_text, source_type, language),
            self._document_control_agent(clean_text, extracted),
            self._tax_agent(clean_text, extracted),
            self._journal_agent(clean_text, extracted),
            self._audit_reviewer_agent(clean_text, extracted),
        ]
        conflicts = self._detect_conflicts(extracted, findings)
        final_confidence = self._weighted_confidence(findings, conflicts)

        return {
            "status": "success",
            "workflow": "gmaws_inspired_accounting_multi_agent",
            "organization_id": organization_id,
            "source_type": source_type,
            "extracted_signals": extracted,
            "agent_findings": [finding.to_dict() for finding in findings],
            "conflicts": conflicts,
            "final_recommendation": {
                "confidence_score": final_confidence,
                "decision": "needs_accountant_review" if conflicts else "ready_for_accountant_approval",
                "auto_posted_to_erp": False,
                "approval_required": True,
                "summary": self._final_summary(extracted, conflicts),
            },
        }

    def _intake_agent(self, text: str, source_type: str, language: str) -> AgentFinding:
        normalized = self._normalize(text)
        doc_keywords = {
            "invoice": ["invoice", "tax invoice", "فاتوره", "فاتورة", "ضريبيه", "ضريبية"],
            "receipt": ["receipt", "ايصال", "إيصال", "سند قبض"],
            "payment_voucher": ["payment voucher", "سند صرف", "voucher"],
            "purchase_order": ["purchase order", "po", "امر شراء", "أمر شراء"],
            "bank_statement": ["bank statement", "كشف حساب", "iban", "حساب بنكي"],
            "journal_entry": ["journal entry", "قيد يوميه", "debit", "credit", "مدين", "دائن"],
            "trial_balance": ["trial balance", "ميزان مراجعه", "ميزان مراجعة"],
            "vendor_bill": ["vendor bill", "supplier bill", "فاتوره مورد", "فاتورة مورد"],
        }
        scores = {name: self._keyword_score(normalized, words) for name, words in doc_keywords.items()}
        detected_type = max(scores, key=scores.get)
        confidence = min(0.95, 0.45 + scores[detected_type] * 0.45)
        if source_type != "manual_text" and source_type != "ocr_text":
            detected_type = source_type
            confidence = max(confidence, 0.72)
        detected_language = "ar" if re.search(r"[\u0600-\u06FF]", text) else "en"
        return AgentFinding(
            agent="IntakeAgent",
            role="document classification and language detection",
            confidence=confidence,
            summary=f"Detected {detected_type} document with {detected_language} text signals.",
            details={"document_type": detected_type, "language": language if language != "auto" else detected_language, "scores": scores},
        )

    def _document_control_agent(self, text: str, extracted: dict[str, Any]) -> AgentFinding:
        missing = []
        for key in ["dates", "amounts"]:
            if not extracted[key]:
                missing.append(key)
        has_party = bool(extracted.get("party_candidates"))
        if not has_party:
            missing.append("party")
        confidence = 0.85 - (0.12 * len(missing))
        return AgentFinding(
            agent="DocumentControlAgent",
            role="required accounting evidence check",
            confidence=max(0.35, confidence),
            summary="Basic accounting evidence is present." if not missing else "Some required evidence is missing or unclear.",
            details={"missing_or_unclear": missing, "party_candidates": extracted.get("party_candidates", [])},
        )

    def _tax_agent(self, text: str, extracted: dict[str, Any]) -> AgentFinding:
        normalized = self._normalize(text)
        vat_signals = any(word in normalized for word in ["vat", "tax", "ضريبه", "ضريبة", "ضريبي", "15%"])
        vat_numbers = re.findall(r"\b3\d{14}\b", text.translate(ARABIC_NUMERIC_TRANSLATION))
        amount_check = self._vat_amount_check(extracted.get("amounts", []))
        confidence = 0.42 + (0.25 if vat_signals else 0) + (0.18 if vat_numbers else 0) + (0.10 if amount_check.get("possible_15_percent_vat") else 0)
        return AgentFinding(
            agent="TaxAgent",
            role="KSA VAT signal review",
            confidence=min(0.95, confidence),
            summary="VAT signals detected; accountant should confirm tax treatment." if vat_signals else "No clear VAT signal detected.",
            details={"vat_signals": vat_signals, "vat_numbers": vat_numbers, "amount_check": amount_check},
        )

    def _journal_agent(self, text: str, extracted: dict[str, Any]) -> AgentFinding:
        normalized = self._normalize(text)
        categories = []
        if any(word in normalized for word in ["rent", "fee", "expense", "مصروف", "رسوم", "ايجار", "إيجار"]):
            categories.append("expense")
        if any(word in normalized for word in ["asset", "fixed asset", "اصل", "أصل"]):
            categories.append("asset")
        if any(word in normalized for word in ["sales", "revenue", "income", "مبيعات", "ايراد", "إيراد"]):
            categories.append("revenue")
        if any(word in normalized for word in ["bank", "iban", "transfer", "بنك", "تحويل"]):
            categories.append("bank_transaction")
        debit = {"code": None, "name": "Expense / Asset clearing", "reason": "Default debit pending accountant review"}
        credit = {"code": None, "name": "Accounts payable / Bank clearing", "reason": "Default credit pending accountant review"}
        if "revenue" in categories:
            debit = {"code": None, "name": "Accounts receivable / Bank", "reason": "Revenue or collection signal detected"}
            credit = {"code": None, "name": "Revenue", "reason": "Revenue signal detected"}
        elif "bank_transaction" in categories:
            debit = {"code": None, "name": "Bank / Counterparty clearing", "reason": "Bank signal detected"}
            credit = {"code": None, "name": "Offset account pending review", "reason": "Needs accountant approval"}
        confidence = 0.55 + (0.08 * min(len(categories), 3)) + (0.08 if extracted.get("amounts") else 0)
        return AgentFinding(
            agent="JournalAgent",
            role="draft journal-entry suggestion",
            confidence=min(0.88, confidence),
            summary="Draft accounting treatment prepared; not posted to ERP.",
            details={"financial_categories": categories, "debit_account": debit, "credit_account": credit, "approval_required": True},
        )

    def _audit_reviewer_agent(self, text: str, extracted: dict[str, Any]) -> AgentFinding:
        review_points = []
        if len(text) < 120:
            review_points.append("OCR/text is short; source document may need manual review.")
        if len(extracted.get("amounts", [])) > 8:
            review_points.append("Many amounts detected; confirm subtotal, VAT, and total mapping.")
        if not extracted.get("dates"):
            review_points.append("No clear transaction date found.")
        confidence = 0.84 - (0.10 * len(review_points))
        return AgentFinding(
            agent="ReviewerAgent",
            role="audit safety and approval gate",
            confidence=max(0.45, confidence),
            summary="No major audit blockers found." if not review_points else "Manual review points were identified.",
            details={"review_points": review_points, "no_auto_posting": True},
        )

    def _extract_financial_signals(self, text: str) -> dict[str, Any]:
        normalized_text = text.translate(ARABIC_NUMERIC_TRANSLATION)
        amounts = []
        for raw in re.findall(r"(?<!\w)(?:SAR|SR|ر\.س|ريال)?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)", normalized_text, flags=re.I):
            try:
                value = Decimal(raw.replace(",", ""))
            except InvalidOperation:
                continue
            if value > 0:
                amounts.append(str(value))
        dates = re.findall(r"\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b", normalized_text)
        refs = re.findall(r"\b(?:INV|PO|JE|BILL|PV|RV)[-/A-Z0-9]*\d+\b", normalized_text, flags=re.I)
        party_candidates = []
        party_match = re.search(r"(?:supplier|vendor|customer|المورد|العميل|اسم المورد)\s*[:\-]?\s*([^\n,]{3,160})", text, flags=re.I)
        if party_match:
            party_candidates.append(party_match.group(1).strip())
        return {
            "amounts": amounts[:20],
            "dates": dates[:10],
            "references": refs[:20],
            "party_candidates": party_candidates[:5],
        }

    def _detect_conflicts(self, extracted: dict[str, Any], findings: list[AgentFinding]) -> list[dict[str, Any]]:
        conflicts: list[dict[str, Any]] = []
        if not extracted.get("amounts"):
            conflicts.append({"type": "missing_amount", "severity": "high", "message": "No financial amount was detected."})
        if not extracted.get("dates"):
            conflicts.append({"type": "missing_date", "severity": "medium", "message": "No clear accounting date was detected."})
        low_confidence_agents = [f.agent for f in findings if f.confidence < 0.55]
        if low_confidence_agents:
            conflicts.append({"type": "low_confidence", "severity": "medium", "message": "Some agents reported low confidence.", "agents": low_confidence_agents})
        return conflicts

    def _vat_amount_check(self, amounts: list[str]) -> dict[str, Any]:
        values = []
        for amount in amounts:
            try:
                values.append(Decimal(amount))
            except InvalidOperation:
                continue
        for subtotal in values:
            vat = (subtotal * Decimal("0.15")).quantize(Decimal("0.01"))
            total = (subtotal + vat).quantize(Decimal("0.01"))
            if vat in values or total in values:
                return {"possible_15_percent_vat": True, "subtotal": str(subtotal), "vat": str(vat), "total": str(total)}
        return {"possible_15_percent_vat": False}

    @staticmethod
    def _keyword_score(normalized_text: str, words: list[str]) -> float:
        if not words:
            return 0.0
        hits = sum(1 for word in words if AccountingMultiAgentOrchestrator._normalize(word) in normalized_text)
        return hits / len(words)

    @staticmethod
    def _normalize(text: str) -> str:
        text = text.translate(ARABIC_NUMERIC_TRANSLATION).lower()
        text = re.sub(r"[إأآا]", "ا", text)
        text = re.sub(r"[ى]", "ي", text)
        text = re.sub(r"[ة]", "ه", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _weighted_confidence(findings: list[AgentFinding], conflicts: list[dict[str, Any]]) -> float:
        base = sum(f.confidence for f in findings) / max(len(findings), 1)
        penalty = 0.08 * len(conflicts)
        return round(max(0.15, min(0.97, base - penalty)), 4)

    @staticmethod
    def _final_summary(extracted: dict[str, Any], conflicts: list[dict[str, Any]]) -> str:
        amount_summary = extracted.get("amounts", [])[:3]
        date_summary = extracted.get("dates", [])[:2]
        if conflicts:
            return f"Workflow completed with {len(conflicts)} review point(s). Amounts={amount_summary}, Dates={date_summary}."
        return f"Workflow completed with no major conflicts. Amounts={amount_summary}, Dates={date_summary}."
