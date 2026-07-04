"""Vector database service using ChromaDB for semantic matching.

Provides persistent vector storage and similarity search for:
- Bank reconciliation (statement ↔ ledger transaction matching)
- Document-to-ERP move matching
- Accounting AI document embedding matching
"""

import hashlib
import logging
import re
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------

_embedding_provider = None


def _get_embedding_provider():
    """Lazily initialise the shared EmbeddingProvider."""
    global _embedding_provider
    if _embedding_provider is None:
        from app.services.accounting_ai import EmbeddingProvider
        _embedding_provider = EmbeddingProvider()
    return _embedding_provider


def embed_text(text: str) -> list[float]:
    """Return a normalised embedding vector for *text*."""
    provider = _get_embedding_provider()
    vector, _ = provider.embed(text)
    return vector


# ---------------------------------------------------------------------------
# Normalisation helpers (Arabic + English, lightweight)
# ---------------------------------------------------------------------------

_ARABIC_NORM = str.maketrans({
    "إ": "ا", "أ": "ا", "آ": "ا",
    "ى": "ي",
    "ة": "ه",
})


def normalize_for_embedding(text: str) -> str:
    """Lower-case, strip diacritics and collapse whitespace."""
    text = (text or "").lower().translate(_ARABIC_NORM)
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _doc_id(prefix: str, text: str, amount: float = 0.0) -> str:
    """Deterministic document id for ChromaDB upsert idempotency."""
    blob = f"{prefix}:{text}:{amount}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# ChromaDB client singleton
# ---------------------------------------------------------------------------

_chroma_client = None


def _get_chroma_client():
    """Return a persistent ChromaDB client (singleton)."""
    global _chroma_client
    if _chroma_client is not None:
        return _chroma_client

    import chromadb

    persist_dir = settings.chroma_persist_path

    try:
        _chroma_client = chromadb.PersistentClient(
            path=persist_dir,
            settings=chromadb.Settings(anonymized_telemetry=False),
        )
    except TypeError:
        _chroma_client = chromadb.PersistentClient(path=persist_dir)

    logger.info("ChromaDB PersistentClient initialised (path=%s)", persist_dir)
    return _chroma_client


def _get_or_create_collection(name: str):
    """Return a ChromaDB collection, creating it if needed."""
    client = _get_chroma_client()
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


# ---------------------------------------------------------------------------
# Collection names
# ---------------------------------------------------------------------------

BANK_RECONCILIATION_COLLECTION = "bank_reconciliation"
DOCUMENT_MATCHING_COLLECTION = "document_matching"
ACCOUNTING_AI_COLLECTION = "accounting_ai_embeddings"


# ---------------------------------------------------------------------------
# Public API: Bank Reconciliation
# ---------------------------------------------------------------------------

def index_bank_transactions(
    transactions: list[dict],
    source: str,
    org_id: int = 1,
) -> int:
    """Index bank transactions (statement or ledger) into the vector DB.

    Each *transaction* dict must contain ``date``, ``description``, and ``amount``.
    *source* should be ``"statement"`` or ``"ledger"``.

    Returns the number of documents upserted.
    """
    collection = _get_or_create_collection(BANK_RECONCILIATION_COLLECTION)

    ids: list[str] = []
    embeddings: list[list[float]] = []
    documents: list[str] = []
    metadatas: list[dict] = []

    for txn in transactions:
        desc = normalize_for_embedding(txn.get("description", ""))
        if not desc:
            continue
        doc_text = f"{txn.get('date', '')} {desc} {txn.get('amount', 0.0)}"
        doc_text_norm = normalize_for_embedding(doc_text)
        vector = embed_text(doc_text_norm)

        doc_id = _doc_id(f"{org_id}:{source}", doc_text_norm, txn.get("amount", 0.0))
        ids.append(doc_id)
        embeddings.append(vector)
        documents.append(doc_text_norm)
        metadatas.append({
            "source": source,
            "org_id": str(org_id),
            "date": str(txn.get("date", "")),
            "amount": float(txn.get("amount", 0.0)),
            "description": str(txn.get("description", ""))[:500],
            "row_number": int(txn.get("row_number", 0)),
        })

    if not ids:
        return 0

    collection.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
    return len(ids)


def search_similar_transactions(
    query_text: str,
    source_filter: str,
    org_id: int = 1,
    n_results: int = 10,
    amount: Optional[float] = None,
) -> list[dict]:
    """Search the vector DB for transactions similar to *query_text*.

    *source_filter*: ``"statement"`` or ``"ledger"`` — the collection side to
    search **against** (i.e. the opposite side from the query).

    Returns a list of dicts with ``id``, ``score``, ``metadata``, ``document``.
    """
    collection = _get_or_create_collection(BANK_RECONCILIATION_COLLECTION)

    query_norm = normalize_for_embedding(query_text)
    if not query_norm:
        return []

    vector = embed_text(query_norm)

    where_filter = {
        "$and": [
            {"source": {"$eq": source_filter}},
            {"org_id": {"$eq": str(org_id)}},
        ]
    }

    try:
        results = collection.query(
            query_embeddings=[vector],
            n_results=n_results,
            where=where_filter,
        )
    except Exception as exc:
        logger.warning("ChromaDB query failed: %s", exc)
        return []

    hits: list[dict] = []
    if not results or not results.get("ids"):
        return hits

    result_ids = results["ids"][0]
    distances = results.get("distances", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    docs = results.get("documents", [[]])[0]

    for i, doc_id in enumerate(result_ids):
        distance = distances[i] if i < len(distances) else 1.0
        similarity = max(0.0, 1.0 - distance)
        meta = metadatas[i] if i < len(metadatas) else {}
        doc = docs[i] if i < len(docs) else ""

        hits.append({
            "id": doc_id,
            "score": round(similarity, 4),
            "metadata": meta,
            "document": doc,
        })

    return hits


# ---------------------------------------------------------------------------
# Public API: Document Matching
# ---------------------------------------------------------------------------

def index_document(
    doc_text: str,
    doc_id_str: str,
    metadata: dict,
    org_id: int = 1,
) -> str:
    """Index a financial document (invoice, receipt, etc.) into the vector DB.

    Returns the document id used in ChromaDB.
    """
    collection = _get_or_create_collection(DOCUMENT_MATCHING_COLLECTION)

    norm_text = normalize_for_embedding(doc_text)
    if not norm_text:
        return ""

    vector = embed_text(norm_text)
    safe_meta = {k: str(v)[:500] if v is not None else "" for k, v in metadata.items()}
    safe_meta["org_id"] = str(org_id)

    doc_id = _doc_id(f"{org_id}:doc", doc_id_str)
    collection.upsert(
        ids=[doc_id],
        embeddings=[vector],
        documents=[norm_text[:2000]],
        metadatas=[safe_meta],
    )
    return doc_id


def search_similar_documents(
    query_text: str,
    org_id: int = 1,
    n_results: int = 10,
) -> list[dict]:
    """Search for documents semantically similar to *query_text*."""
    collection = _get_or_create_collection(DOCUMENT_MATCHING_COLLECTION)

    query_norm = normalize_for_embedding(query_text)
    if not query_norm:
        return []

    vector = embed_text(query_norm)

    try:
        results = collection.query(
            query_embeddings=[vector],
            n_results=n_results,
            where={"org_id": {"$eq": str(org_id)}},
        )
    except Exception as exc:
        logger.warning("ChromaDB document query failed: %s", exc)
        return []

    hits: list[dict] = []
    if not results or not results.get("ids"):
        return hits

    for i, doc_id in enumerate(results["ids"][0]):
        distance = results.get("distances", [[]])[0][i] if results.get("distances") else 1.0
        similarity = max(0.0, 1.0 - distance)
        meta = results.get("metadatas", [[]])[0][i] if results.get("metadatas") else {}
        doc = results.get("documents", [[]])[0][i] if results.get("documents") else ""
        hits.append({
            "id": doc_id,
            "score": round(similarity, 4),
            "metadata": meta,
            "document": doc,
        })

    return hits


# ---------------------------------------------------------------------------
# Public API: Accounting AI Embeddings
# ---------------------------------------------------------------------------

def index_accounting_embedding(
    text: str,
    embedding_id: int,
    metadata: dict,
    org_id: int = 1,
    vector: Optional[list[float]] = None,
) -> str:
    """Index an accounting AI document embedding into ChromaDB.

    If *vector* is provided it is used directly; otherwise a new embedding is
    computed from *text*.
    """
    collection = _get_or_create_collection(ACCOUNTING_AI_COLLECTION)

    norm_text = normalize_for_embedding(text)
    if not norm_text:
        return ""

    if vector is None:
        vector = embed_text(norm_text)

    safe_meta = {k: str(v)[:500] if v is not None else "" for k, v in metadata.items()}
    safe_meta["org_id"] = str(org_id)

    doc_id = f"ai_emb_{org_id}_{embedding_id}"
    collection.upsert(
        ids=[doc_id],
        embeddings=[vector],
        documents=[norm_text[:2000]],
        metadatas=[safe_meta],
    )
    return doc_id


def search_accounting_embeddings(
    vector: list[float],
    org_id: int = 1,
    n_results: int = 20,
    exclude_id: Optional[int] = None,
) -> list[dict]:
    """Search for similar accounting document embeddings."""
    collection = _get_or_create_collection(ACCOUNTING_AI_COLLECTION)

    try:
        results = collection.query(
            query_embeddings=[vector],
            n_results=n_results + (1 if exclude_id else 0),
            where={"org_id": {"$eq": str(org_id)}},
        )
    except Exception as exc:
        logger.warning("ChromaDB accounting AI query failed: %s", exc)
        return []

    hits: list[dict] = []
    if not results or not results.get("ids"):
        return hits

    exclude_doc_id = f"ai_emb_{org_id}_{exclude_id}" if exclude_id else None

    for i, doc_id in enumerate(results["ids"][0]):
        if doc_id == exclude_doc_id:
            continue
        distance = results.get("distances", [[]])[0][i] if results.get("distances") else 1.0
        similarity = max(0.0, 1.0 - distance)
        meta = results.get("metadatas", [[]])[0][i] if results.get("metadatas") else {}
        doc = results.get("documents", [[]])[0][i] if results.get("documents") else ""
        hits.append({
            "id": doc_id,
            "score": round(similarity, 4),
            "metadata": meta,
            "document": doc,
        })

    return hits[:n_results]
