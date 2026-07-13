"""Tenant-isolated semantic vector storage backed by the application database.

This module intentionally avoids running or embedding a separate ChromaDB server. The
application stores vectors under the same PostgreSQL authorization, backup, audit, and
network boundary as the accounting data. Similarity is calculated in-process for the
bounded candidate set. A dedicated managed vector service can replace this adapter in
the future after an explicit security review.
"""

import hashlib
import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.core import VectorRecord

logger = logging.getLogger(__name__)

_embedding_provider = None
_embedding_unavailable = False
_EMBED_INIT_TIMEOUT_SECONDS = 15
_MAX_SEARCH_CANDIDATES = 5_000

BANK_RECONCILIATION_COLLECTION = "bank_reconciliation"
DOCUMENT_MATCHING_COLLECTION = "document_matching"
ACCOUNTING_AI_COLLECTION = "accounting_ai_embeddings"

_ARABIC_NORM = str.maketrans(
    {
        "إ": "ا",
        "أ": "ا",
        "آ": "ا",
        "ى": "ي",
        "ة": "ه",
    }
)


def _get_embedding_provider():
    global _embedding_provider
    if _embedding_provider is None:
        from app.services.accounting_ai import EmbeddingProvider

        _embedding_provider = EmbeddingProvider()
    return _embedding_provider


def _embed_text_sync(text: str) -> list[float]:
    provider = _get_embedding_provider()
    vector, _ = provider.embed(text)
    return [float(value) for value in vector]


def embed_text(text: str) -> list[float]:
    """Generate an embedding with a hard initialization timeout and circuit breaker."""
    global _embedding_unavailable
    if _embedding_unavailable:
        raise RuntimeError("Embedding provider unavailable (circuit-breaker open)")

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_embed_text_sync, text)
        return future.result(timeout=_EMBED_INIT_TIMEOUT_SECONDS)
    except FuturesTimeoutError as exc:
        _embedding_unavailable = True
        logger.warning(
            "Embedding initialization timed out after %ss; vector matching disabled for this process.",
            _EMBED_INIT_TIMEOUT_SECONDS,
        )
        raise RuntimeError("Embedding initialization timed out") from exc
    except Exception as exc:
        if _embedding_provider is None or getattr(_embedding_provider, "_model", None) is None:
            _embedding_unavailable = True
            logger.warning("Embedding initialization failed; vector matching disabled: %s", exc)
        raise
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def normalize_for_embedding(text: str) -> str:
    text = (text or "").lower().translate(_ARABIC_NORM)
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _doc_id(prefix: str, text: str, amount: float = 0.0) -> str:
    blob = f"{prefix}:{text}:{amount}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _clean_vector(vector: list[float]) -> list[float]:
    cleaned = [float(value) for value in vector]
    if not cleaned or len(cleaned) > 8_192:
        raise ValueError("Embedding vector has an invalid dimension")
    if any(not math.isfinite(value) for value in cleaned):
        raise ValueError("Embedding vector contains a non-finite value")
    return cleaned


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


def _upsert_record(
    db: Session,
    *,
    collection_name: str,
    organization_id: int,
    document_key: str,
    document: str,
    metadata: dict,
    embedding: list[float],
) -> None:
    record = (
        db.query(VectorRecord)
        .filter(
            VectorRecord.organization_id == organization_id,
            VectorRecord.collection_name == collection_name,
            VectorRecord.document_key == document_key,
        )
        .first()
    )
    clean_embedding = _clean_vector(embedding)
    clean_document = (document or "")[:20_000]
    clean_metadata = dict(metadata)

    if record is None:
        db.add(
            VectorRecord(
                organization_id=organization_id,
                collection_name=collection_name,
                document_key=document_key,
                document=clean_document,
                record_metadata=clean_metadata,
                embedding=clean_embedding,
            )
        )
    else:
        record.document = clean_document
        record.record_metadata = clean_metadata
        record.embedding = clean_embedding


def _search_records(
    *,
    collection_name: str,
    organization_id: int,
    query_vector: list[float],
    n_results: int,
    metadata_predicate: Callable[[dict], bool] | None = None,
    exclude_document_key: str | None = None,
) -> list[dict]:
    safe_limit = max(1, min(int(n_results), 100))
    clean_query = _clean_vector(query_vector)
    db = SessionLocal()
    try:
        records = (
            db.query(VectorRecord)
            .filter(
                VectorRecord.organization_id == organization_id,
                VectorRecord.collection_name == collection_name,
            )
            .order_by(VectorRecord.id.desc())
            .limit(_MAX_SEARCH_CANDIDATES)
            .all()
        )

        hits: list[dict] = []
        for record in records:
            if exclude_document_key and record.document_key == exclude_document_key:
                continue
            metadata = record.record_metadata or {}
            if metadata_predicate and not metadata_predicate(metadata):
                continue
            try:
                score = _cosine_similarity(clean_query, [float(v) for v in record.embedding])
            except (TypeError, ValueError):
                logger.warning("Skipping malformed vector record id=%s", record.id)
                continue
            hits.append(
                {
                    "id": record.document_key,
                    "score": round(max(0.0, score), 4),
                    "metadata": metadata,
                    "document": record.document,
                }
            )

        hits.sort(key=lambda item: item["score"], reverse=True)
        return hits[:safe_limit]
    finally:
        db.close()


def index_bank_transactions(
    transactions: list[dict],
    source: str,
    org_id: int = 1,
) -> int:
    if source not in {"statement", "ledger"}:
        raise ValueError("source must be 'statement' or 'ledger'")

    db = SessionLocal()
    indexed = 0
    try:
        for txn in transactions:
            description = normalize_for_embedding(str(txn.get("description", "")))
            if not description:
                continue
            amount = float(txn.get("amount", 0.0) or 0.0)
            document = normalize_for_embedding(
                f"{txn.get('date', '')} {description} {amount}"
            )
            vector = embed_text(document)
            document_key = _doc_id(f"{org_id}:{source}", document, amount)
            _upsert_record(
                db,
                collection_name=BANK_RECONCILIATION_COLLECTION,
                organization_id=org_id,
                document_key=document_key,
                document=document,
                metadata={
                    "source": source,
                    "org_id": str(org_id),
                    "date": str(txn.get("date", "")),
                    "amount": amount,
                    "description": str(txn.get("description", ""))[:500],
                    "row_number": int(txn.get("row_number", 0) or 0),
                },
                embedding=vector,
            )
            indexed += 1
        db.commit()
        return indexed
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def search_similar_transactions(
    query_text: str,
    source_filter: str,
    org_id: int = 1,
    n_results: int = 10,
    amount: Optional[float] = None,
) -> list[dict]:
    del amount  # Preserved for API compatibility; ranking remains embedding-based.
    if source_filter not in {"statement", "ledger"}:
        return []
    query = normalize_for_embedding(query_text)
    if not query:
        return []
    return _search_records(
        collection_name=BANK_RECONCILIATION_COLLECTION,
        organization_id=org_id,
        query_vector=embed_text(query),
        n_results=n_results,
        metadata_predicate=lambda metadata: metadata.get("source") == source_filter,
    )


def index_document(
    doc_text: str,
    doc_id_str: str,
    metadata: dict,
    org_id: int = 1,
) -> str:
    normalized = normalize_for_embedding(doc_text)
    if not normalized:
        return ""
    document_key = _doc_id(f"{org_id}:doc", doc_id_str)
    safe_metadata = {
        key: str(value)[:500] if value is not None else ""
        for key, value in metadata.items()
    }
    safe_metadata["org_id"] = str(org_id)

    db = SessionLocal()
    try:
        _upsert_record(
            db,
            collection_name=DOCUMENT_MATCHING_COLLECTION,
            organization_id=org_id,
            document_key=document_key,
            document=normalized[:2_000],
            metadata=safe_metadata,
            embedding=embed_text(normalized),
        )
        db.commit()
        return document_key
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def search_similar_documents(
    query_text: str,
    org_id: int = 1,
    n_results: int = 10,
) -> list[dict]:
    normalized = normalize_for_embedding(query_text)
    if not normalized:
        return []
    return _search_records(
        collection_name=DOCUMENT_MATCHING_COLLECTION,
        organization_id=org_id,
        query_vector=embed_text(normalized),
        n_results=n_results,
    )


def index_accounting_embedding(
    text: str,
    embedding_id: int,
    metadata: dict,
    org_id: int = 1,
    vector: Optional[list[float]] = None,
) -> str:
    normalized = normalize_for_embedding(text)
    if not normalized:
        return ""
    safe_metadata = {
        key: str(value)[:500] if value is not None else ""
        for key, value in metadata.items()
    }
    safe_metadata["org_id"] = str(org_id)
    document_key = f"ai_emb_{org_id}_{embedding_id}"

    db = SessionLocal()
    try:
        _upsert_record(
            db,
            collection_name=ACCOUNTING_AI_COLLECTION,
            organization_id=org_id,
            document_key=document_key,
            document=normalized[:2_000],
            metadata=safe_metadata,
            embedding=vector if vector is not None else embed_text(normalized),
        )
        db.commit()
        return document_key
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def search_accounting_embeddings(
    vector: list[float],
    org_id: int = 1,
    n_results: int = 20,
    exclude_id: Optional[int] = None,
) -> list[dict]:
    exclude_document_key = f"ai_emb_{org_id}_{exclude_id}" if exclude_id else None
    return _search_records(
        collection_name=ACCOUNTING_AI_COLLECTION,
        organization_id=org_id,
        query_vector=vector,
        n_results=n_results,
        exclude_document_key=exclude_document_key,
    )
