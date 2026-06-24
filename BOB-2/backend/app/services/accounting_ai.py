from __future__ import annotations

import hashlib
import os
import math
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models.ai_accounting import AIAccountingSuggestion, AIDecisionAuditLog, AIDocumentEmbedding, AIDocumentMatch

DOC_LABELS = {"invoice": ["invoice", "tax invoice", "فاتورة", "ضريبية"], "receipt": ["receipt", "ايصال", "إيصال", "سند قبض"], "payment_voucher": ["payment voucher", "سند صرف", "voucher"], "purchase_order": ["purchase order", "po", "أمر شراء"], "bank_statement": ["bank statement", "كشف حساب", "حساب بنكي", "iban"], "journal_entry": ["journal entry", "قيد يومية", "debit", "credit", "مدين", "دائن"], "trial_balance": ["trial balance", "ميزان مراجعة"], "vendor_bill": ["vendor bill", "supplier bill", "فاتورة مورد"]}
CATEGORIES = {"payment": ["paid", "payment", "سداد", "دفع", "تحويل"], "accrual": ["accrual", "accrued", "مستحق"], "expense": ["expense", "fee", "rent", "مصروف", "رسوم", "ايجار", "إيجار"], "asset": ["asset", "fixed asset", "أصل", "اصول"], "liability": ["liability", "payable", "التزام", "دائنون"], "revenue": ["revenue", "sales", "income", "مبيعات", "ايراد", "إيراد"], "bank_transaction": ["bank", "iban", "transfer", "بنك", "تحويل"], "payroll": ["salary", "payroll", "wage", "راتب", "رواتب"], "petty_cash": ["petty cash", "cash", "عهدة", "نقد"]}


def normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[إأآا]", "ا", text)
    text = re.sub(r"[ى]", "ي", text)
    text = re.sub(r"[ة]", "ه", text)
    return re.sub(r"\s+", " ", text).strip()


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 0.0 if na == 0 or nb == 0 else dot / (na * nb)


class EmbeddingProvider:
    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-m3")
        self._model = None

    def embed(self, text: str) -> tuple[list[float], str]:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            if self._model is None:
                self._model = SentenceTransformer(self.model_name)
            vector = self._model.encode([text], normalize_embeddings=True)[0].tolist()
            return [float(v) for v in vector], self.model_name
        except Exception:
            return self._local_accounting_embedding(text, 1024), f"local-accounting-hash-fallback:{self.model_name}"

    @staticmethod
    def _local_accounting_embedding(text: str, dim: int) -> list[float]:
        vector = [0.0] * dim
        for token in re.findall(r"[\w\u0600-\u06FF]+", normalize_text(text)):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % dim
            vector[idx] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


@dataclass
class AnalysisResult:
    embedding: AIDocumentEmbedding
    matches: list[AIDocumentMatch]
    suggestion: AIAccountingSuggestion


class AccountingAIMatchingService:
    def __init__(self, db: Session, provider: EmbeddingProvider | None = None):
        self.db = db
        self.provider = provider or EmbeddingProvider()

    def analyze_document(self, *, text: str, source_type: str, organization_id: int = 1, document_id: int | None = None, source_reference: str | None = None) -> AnalysisResult:
        clean_text = text.strip()
        if len(clean_text) < 8:
            raise ValueError("Document text is too short for accounting AI matching.")
        vector, model_name = self.provider.embed(clean_text)
        classification = self.classify(clean_text)
        embedding = AIDocumentEmbedding(organization_id=organization_id, document_id=document_id, source_type=source_type, source_reference=source_reference, text_hash=hashlib.sha256(clean_text.encode("utf-8")).hexdigest(), text_preview=clean_text[:2000], embedding_model=model_name, embedding_dimension=len(vector), embedding_vector=vector, classification=classification, confidence_score=classification["confidence_score"])
        self.db.add(embedding)
        self.db.flush()
        matches = self._create_matches(embedding, vector, classification)
        suggestion = self._create_journal_suggestion(embedding, classification)
        self._audit(embedding.organization_id, "document_analysis", "ai_document_embeddings", str(embedding.id), embedding.confidence_score, "Classified and embedded accounting document text.", {"classification": classification})
        self.db.commit()
        return AnalysisResult(embedding=embedding, matches=matches, suggestion=suggestion)

    def classify(self, text: str) -> dict[str, Any]:
        n = normalize_text(text)
        def score(words: list[str]) -> float:
            return sum(1 for w in words if normalize_text(w) in n) / max(len(words), 1)
        doc_scores = {k: score(v) for k, v in DOC_LABELS.items()}
        document_type = max(doc_scores, key=doc_scores.get)
        category_scores = {k: score(v) for k, v in CATEGORIES.items()}
        categories = [k for k, v in category_scores.items() if v > 0]
        vat_relevant = any(k in n for k in ["vat", "tax", "ضريبه", "ضريبي", "ضريبة", "15%"])
        party_match = re.search(r"(?:supplier|vendor|customer|المورد|العميل)\s*[:\-]?\s*([^\n,]+)", text, re.I)
        confidence = min(0.98, 0.45 + max(doc_scores.values()) * 0.35 + (0.12 if categories else 0) + (0.06 if vat_relevant else 0))
        return {"document_type": document_type, "detected_party": party_match.group(1).strip()[:160] if party_match else None, "vat_relevant": vat_relevant, "financial_categories": categories, "confidence_score": round(confidence, 4), "signals": {"document_type_scores": doc_scores, "category_scores": category_scores}}

    def _create_matches(self, embedding: AIDocumentEmbedding, vector: list[float], classification: dict[str, Any]) -> list[AIDocumentMatch]:
        candidates = self.db.query(AIDocumentEmbedding).filter(AIDocumentEmbedding.organization_id == embedding.organization_id, AIDocumentEmbedding.id != embedding.id).order_by(AIDocumentEmbedding.created_at.desc()).limit(100).all()
        matches: list[AIDocumentMatch] = []
        for candidate in candidates:
            similarity = cosine(vector, candidate.embedding_vector)
            if similarity < 0.62:
                continue
            match_type = self._match_type(classification["document_type"], candidate.classification.get("document_type"))
            explanation = f"Semantic similarity {similarity:.2f} between {classification['document_type']} and {candidate.classification.get('document_type')} with comparable accounting wording/party context."
            match = AIDocumentMatch(organization_id=embedding.organization_id, source_embedding_id=embedding.id, target_embedding_id=candidate.id, match_type=match_type, confidence_score=round(min(0.99, similarity), 4), similarity_score=round(similarity, 4), explanation=explanation, status="pending", match_metadata={"source_type": embedding.source_type, "target_source_type": candidate.source_type})
            self.db.add(match)
            matches.append(match)
            self._audit(embedding.organization_id, "match_suggested", "ai_document_matches", None, match.confidence_score, explanation, {"target_embedding_id": candidate.id})
        return matches

    @staticmethod
    def _match_type(a: str, b: str | None) -> str:
        pair = {a, b or ""}
        if {"invoice", "purchase_order"}.issubset(pair):
            return "invoice_to_po"
        if "bank_statement" in pair:
            return "bank_transaction_to_invoice_or_payment"
        if "payment_voucher" in pair and ("invoice" in pair or "vendor_bill" in pair):
            return "invoice_to_payment_voucher"
        return "semantic_financial_document_match"

    def _create_journal_suggestion(self, embedding: AIDocumentEmbedding, classification: dict[str, Any]) -> AIAccountingSuggestion:
        cats = set(classification["financial_categories"])
        doc_type = classification["document_type"]
        debit = {"code": None, "name": "Expense / Asset clearing", "reason": "Default debit side pending accountant review"}
        credit = {"code": None, "name": "Accounts payable / Bank clearing", "reason": "Default credit side pending accountant review"}
        if "revenue" in cats:
            debit, credit = {"code": None, "name": "Accounts receivable / Bank", "reason": "Revenue collection or invoice signal"}, {"code": None, "name": "Revenue", "reason": "Revenue keywords detected"}
        elif "bank_transaction" in cats or doc_type == "bank_statement":
            debit, credit = {"code": None, "name": "Bank / Counterparty clearing", "reason": "Bank transaction detected"}, {"code": None, "name": "Offset account pending review", "reason": "Requires accountant approval"}
        elif "asset" in cats:
            debit = {"code": None, "name": "Fixed asset", "reason": "Asset keywords detected"}
        vat = {"code": None, "name": "VAT input/output account", "reason": "VAT/tax invoice relevance detected"} if classification["vat_relevant"] else None
        explanation = "Draft journal-entry suggestion only; it is not posted to ERP and requires explicit approval."
        suggestion = AIAccountingSuggestion(organization_id=embedding.organization_id, document_embedding_id=embedding.id, status="draft", confidence_score=classification["confidence_score"], explanation=explanation, debit_account=debit, credit_account=credit, vat_account=vat, suggestion_payload={"document_type": doc_type, "financial_categories": list(cats), "approval_required": True})
        self.db.add(suggestion)
        self._audit(embedding.organization_id, "journal_suggestion_drafted", "ai_accounting_suggestions", None, suggestion.confidence_score, explanation, suggestion.suggestion_payload)
        return suggestion

    def update_decision_status(self, entity: str, entity_id: int, status: str, organization_id: int = 1) -> dict[str, Any]:
        if status not in {"approved", "rejected", "pending", "draft"}:
            raise ValueError("Invalid AI decision status.")
        model = AIDocumentMatch if entity == "match" else AIAccountingSuggestion
        obj = self.db.query(model).filter(model.id == entity_id, model.organization_id == organization_id).first()
        if not obj:
            raise ValueError("AI decision entity not found.")
        obj.status = status
        self._audit(organization_id, "decision_status_updated", entity, str(entity_id), obj.confidence_score, f"AI {entity} marked {status}; no ERP posting was performed.", {"status": status})
        self.db.commit()
        return {"id": entity_id, "entity": entity, "status": status}

    def _audit(self, organization_id: int, decision_type: str, entity_type: str, entity_id: str | None, confidence: float, explanation: str, payload: dict[str, Any]) -> None:
        self.db.add(AIDecisionAuditLog(organization_id=organization_id, decision_type=decision_type, entity_type=entity_type, entity_id=entity_id, confidence_score=confidence, explanation=explanation, payload=payload))
