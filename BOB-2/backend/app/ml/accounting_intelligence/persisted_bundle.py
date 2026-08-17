"""Verified persisted accounting-model loading and inference.

The production service must never deserialize an arbitrary joblib/pickle artifact.
This module verifies the exact SHA-256 and model version selected by the locked
holdout evaluation before loading the bundle.  It has no ERP mutation capability.
"""

from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np
from scipy import sparse
from sklearn.preprocessing import normalize

from app.ml.accounting_intelligence.contracts import AccountingReferenceCatalog

DEFAULT_BUNDLE_PATH = Path(
    "/data/storage/odoo-training-dataset/models/accounting_ml_v2/"
    "accounting_model_bundle_v2.joblib"
)
DEFAULT_BUNDLE_SHA256 = "217f893a5479209f508b42aec8e5c84c1b4f868639026f22703ff47e8b3bbc35"
DEFAULT_MODEL_VERSION = "accounting-ml-v2.0.0"
MAX_BUNDLE_BYTES = 200 * 1024 * 1024


class PersistedAccountingModelError(RuntimeError):
    """Raised when the trusted persisted accounting model cannot be used safely."""


@dataclass(frozen=True)
class PersistedBundleIdentity:
    path: str
    sha256: str
    model_version: str
    size_bytes: int


class VerifiedAccountingBundleLoader:
    """Loads exactly one reviewed model artifact and caches it process-locally."""

    def __init__(
        self,
        *,
        path: str | Path | None = None,
        expected_sha256: str | None = None,
        expected_model_version: str | None = None,
    ) -> None:
        configured_path = path or os.getenv("ACCOUNTING_ML_BUNDLE_PATH") or DEFAULT_BUNDLE_PATH
        self.path = Path(configured_path)
        self.expected_sha256 = (
            expected_sha256
            or os.getenv("ACCOUNTING_ML_BUNDLE_SHA256")
            or DEFAULT_BUNDLE_SHA256
        ).strip().lower()
        self.expected_model_version = (
            expected_model_version
            or os.getenv("ACCOUNTING_ML_MODEL_VERSION")
            or DEFAULT_MODEL_VERSION
        ).strip()
        self._lock = threading.Lock()
        self._bundle: dict[str, Any] | None = None
        self._identity: PersistedBundleIdentity | None = None
        self._stat_signature: tuple[int, int] | None = None

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _validate_file(self) -> tuple[int, int]:
        try:
            stat = self.path.stat()
        except FileNotFoundError as exc:
            raise PersistedAccountingModelError(
                f"Persisted accounting model is missing: {self.path}"
            ) from exc
        if not self.path.is_file():
            raise PersistedAccountingModelError(
                f"Persisted accounting model path is not a regular file: {self.path}"
            )
        if stat.st_size <= 0 or stat.st_size > MAX_BUNDLE_BYTES:
            raise PersistedAccountingModelError(
                f"Persisted accounting model has an invalid size: {stat.st_size} bytes"
            )
        return int(stat.st_mtime_ns), int(stat.st_size)

    def load(self) -> dict[str, Any]:
        stat_signature = self._validate_file()
        with self._lock:
            if self._bundle is not None and self._stat_signature == stat_signature:
                return self._bundle

            actual_sha256 = self._sha256(self.path)
            if actual_sha256.lower() != self.expected_sha256:
                raise PersistedAccountingModelError(
                    "Persisted accounting model SHA-256 does not match the locked, "
                    "holdout-evaluated artifact."
                )

            # joblib/pickle deserialization happens only after cryptographic identity
            # verification of the locally mounted artifact above.
            bundle = joblib.load(self.path)
            if not isinstance(bundle, dict):
                raise PersistedAccountingModelError("Persisted accounting model bundle is not a mapping.")

            metadata = bundle.get("metadata") or {}
            model_version = str(metadata.get("model_version") or "")
            if model_version != self.expected_model_version:
                raise PersistedAccountingModelError(
                    "Persisted accounting model version does not match the locked version: "
                    f"{model_version!r}."
                )
            if not isinstance(bundle.get("vectorizers"), dict) or not isinstance(bundle.get("tasks"), dict):
                raise PersistedAccountingModelError(
                    "Persisted accounting model is missing vectorizers or task definitions."
                )

            self._bundle = bundle
            self._stat_signature = stat_signature
            self._identity = PersistedBundleIdentity(
                path=str(self.path),
                sha256=actual_sha256,
                model_version=model_version,
                size_bytes=stat_signature[1],
            )
            return bundle

    def identity(self) -> PersistedBundleIdentity:
        self.load()
        assert self._identity is not None
        return self._identity

    def status(self) -> dict[str, Any]:
        try:
            identity = self.identity()
            return {
                "available": True,
                "verified": True,
                "model_version": identity.model_version,
                "sha256": identity.sha256,
                "path": identity.path,
                "size_bytes": identity.size_bytes,
                "error": None,
            }
        except Exception as exc:
            return {
                "available": False,
                "verified": False,
                "model_version": self.expected_model_version,
                "sha256": self.expected_sha256,
                "path": str(self.path),
                "size_bytes": None,
                "error": type(exc).__name__,
            }


class _CatalogResolver:
    """Resolves stable model labels to current ERP references without mutation."""

    def __init__(self, catalog: AccountingReferenceCatalog) -> None:
        self.catalog = catalog
        self._accounts = self._index(catalog.accounts, ("code", "name"))
        self._journals = self._index(catalog.journals, ("code", "name"))
        self._taxes = self._index(catalog.taxes, ("name", "description"))
        self._analytics = self._index(catalog.analytic_accounts, ("code", "name"))

    @staticmethod
    def _key(value: Any) -> str:
        return str(value or "").strip().casefold()

    @classmethod
    def _index(
        cls,
        rows: Iterable[dict[str, Any]],
        fields: tuple[str, ...],
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            for field in fields:
                key = cls._key(row.get(field))
                if key and key not in result:
                    result[key] = dict(row)
        return result

    def resolve(self, task_name: str, label: str) -> dict[str, Any] | None:
        key = self._key(label)
        if task_name in {"debit_accounts", "credit_accounts"}:
            return self._accounts.get(key)
        if task_name == "journal":
            return self._journals.get(key)
        if task_name == "taxes":
            return self._taxes.get(key)
        if task_name == "analytics":
            return self._analytics.get(key)
        return None


class PersistedAccountingPredictor:
    """Runs the locked V2 model in Load -> Predict mode only."""

    def __init__(self, loader: VerifiedAccountingBundleLoader | None = None) -> None:
        self.loader = loader or VerifiedAccountingBundleLoader()

    @staticmethod
    def _sigmoid(values: np.ndarray) -> np.ndarray:
        clipped = np.clip(values, -20.0, 20.0)
        return 1.0 / (1.0 + np.exp(-clipped))

    @staticmethod
    def _softmax(values: np.ndarray) -> np.ndarray:
        shifted = values - np.max(values, axis=1, keepdims=True)
        exp = np.exp(np.clip(shifted, -40.0, 40.0))
        denom = exp.sum(axis=1, keepdims=True)
        denom[denom == 0] = 1.0
        return exp / denom

    @staticmethod
    def _model_text(text: str, documents: list[dict[str, Any]] | None) -> str:
        docs = documents or []
        tags: list[str] = [f"__doc_count_{min(len(docs) if docs else 1, 10)}"]
        has_ocr = False
        for doc in docs:
            extractor = str(doc.get("extractor") or "unknown").lower()
            ext = str(doc.get("extension") or "none").lower().lstrip(".")
            mime = str(doc.get("mime") or "unknown").lower().replace("/", "_")
            tags.append(f"__extractor_{extractor}")
            tags.append(f"__ext_{ext}")
            tags.append(f"__mime_{mime}")
            if int(doc.get("ocr_pages") or 0) > 0:
                has_ocr = True
        tags.append("__has_ocr" if has_ocr else "__no_ocr")
        return " ".join(tags) + "\n" + text

    @staticmethod
    def _transform(bundle: dict[str, Any], model_text: str) -> sparse.csr_matrix:
        vectorizers = bundle["vectorizers"]
        word = vectorizers["word"].transform([model_text])
        char = vectorizers["char"].transform([model_text])
        matrix = sparse.hstack((word, char), format="csr", dtype=np.float32)
        return normalize(matrix, norm="l2", copy=False).tocsr()

    @staticmethod
    def _neighbors(
        query: sparse.csr_matrix,
        train: sparse.csr_matrix,
        max_k: int = 5,
    ) -> tuple[np.ndarray, np.ndarray]:
        similarities = (query @ train.T).toarray().astype(np.float32, copy=False)
        k = min(max_k, similarities.shape[1])
        indices = np.argpartition(similarities, -k, axis=1)[:, -k:]
        row = np.arange(similarities.shape[0])[:, None]
        values = similarities[row, indices]
        order = np.argsort(values, axis=1)[:, ::-1]
        return indices[row, order], values[row, order]

    @staticmethod
    def _retrieval_multi_scores(
        train_label_matrix: np.ndarray,
        neighbor_idx: np.ndarray,
        neighbor_sim: np.ndarray,
        k: int,
    ) -> np.ndarray:
        out = np.zeros((neighbor_idx.shape[0], train_label_matrix.shape[1]), dtype=np.float32)
        for row in range(neighbor_idx.shape[0]):
            idx = neighbor_idx[row, :k]
            weights = np.maximum(neighbor_sim[row, :k], 1e-6).astype(np.float32)
            denom = float(weights.sum()) or 1.0
            out[row] = (
                train_label_matrix[idx].astype(np.float32) * weights[:, None]
            ).sum(axis=0) / denom
        return out

    @staticmethod
    def _retrieval_single_scores(
        train_labels: list[str],
        neighbor_idx: np.ndarray,
        neighbor_sim: np.ndarray,
        k: int,
    ) -> dict[str, float]:
        votes: dict[str, float] = {}
        total = 0.0
        for idx, sim in zip(neighbor_idx[0, :k], neighbor_sim[0, :k], strict=True):
            weight = max(float(sim), 1e-6)
            label = str(train_labels[int(idx)])
            votes[label] = votes.get(label, 0.0) + weight
            total += weight
        if total <= 0:
            return {}
        return {label: score / total for label, score in votes.items()}

    @staticmethod
    def _enrich_candidate(
        *,
        task_name: str,
        label: str,
        score: float,
        selected: bool,
        rank: int,
        resolver: _CatalogResolver,
    ) -> dict[str, Any]:
        row = resolver.resolve(task_name, label)
        candidate: dict[str, Any] = {
            "label": label,
            "model_score": round(float(score), 6),
            "selected": bool(selected),
            "rank": int(rank),
            "live_reference_resolved": row is not None,
        }
        if row is not None:
            for field in (
                "id",
                "code",
                "name",
                "description",
                "type",
                "account_type",
                "amount",
                "type_tax_use",
            ):
                if field in row:
                    candidate[field] = row.get(field)
        return candidate

    def _single_candidates(
        self,
        *,
        task_name: str,
        task: dict[str, Any],
        x: sparse.csr_matrix,
        resolver: _CatalogResolver,
        neighbors: np.ndarray | None,
        similarities: np.ndarray | None,
        top_k: int,
    ) -> list[dict[str, Any]]:
        strategy = str(task.get("strategy") or "linear")
        model = task["model"]
        if strategy == "retrieval":
            if neighbors is None or similarities is None:
                raise PersistedAccountingModelError("Retrieval strategy is missing its train index.")
            raw = self._retrieval_single_scores(
                task.get("train_labels") or [],
                neighbors,
                similarities,
                int(task.get("retrieval_k") or 1),
            )
        else:
            classes = [str(value) for value in model.classes_.tolist()]
            try:
                probabilities = np.asarray(model.predict_proba(x), dtype=np.float32)
            except Exception:
                decision = np.asarray(model.decision_function(x), dtype=np.float32)
                if decision.ndim == 1:
                    decision = decision.reshape(1, -1)
                probabilities = self._softmax(decision)
            raw = {label: float(probabilities[0, idx]) for idx, label in enumerate(classes)}

        ranked = sorted(raw.items(), key=lambda item: item[1], reverse=True)[:top_k]
        return [
            self._enrich_candidate(
                task_name=task_name,
                label=label,
                score=score,
                selected=rank == 1,
                rank=rank,
                resolver=resolver,
            )
            for rank, (label, score) in enumerate(ranked, start=1)
        ]

    def _multi_candidates(
        self,
        *,
        task_name: str,
        task: dict[str, Any],
        x: sparse.csr_matrix,
        resolver: _CatalogResolver,
        neighbors: np.ndarray | None,
        similarities: np.ndarray | None,
        top_k: int,
    ) -> list[dict[str, Any]]:
        model = task["model"]
        strategy = str(task.get("strategy") or "linear")
        linear_scores = np.asarray(model.decision_function(x), dtype=np.float32)
        if linear_scores.ndim == 1:
            linear_scores = linear_scores.reshape(1, -1)

        if strategy == "linear":
            ranking_scores = self._sigmoid(linear_scores)
            selected_mask = linear_scores >= float(task["threshold"])
        else:
            if neighbors is None or similarities is None:
                raise PersistedAccountingModelError("Hybrid/retrieval strategy is missing its train index.")
            retrieval_scores = self._retrieval_multi_scores(
                task["train_label_matrix"],
                neighbors,
                similarities,
                int(task.get("retrieval_k") or 1),
            )
            if strategy == "retrieval":
                ranking_scores = retrieval_scores
            else:
                weight = float(task.get("blend_weight") or 0.0)
                ranking_scores = weight * self._sigmoid(linear_scores) + (1.0 - weight) * retrieval_scores
            selected_mask = ranking_scores >= float(task["threshold"])

        classes = [str(value) for value in task["binarizer"].classes_.tolist()]
        order = np.argsort(ranking_scores[0])[::-1][:top_k]
        return [
            self._enrich_candidate(
                task_name=task_name,
                label=classes[int(index)],
                score=float(ranking_scores[0, int(index)]),
                selected=bool(selected_mask[0, int(index)]),
                rank=rank,
                resolver=resolver,
            )
            for rank, index in enumerate(order, start=1)
        ]

    def predict(
        self,
        *,
        text: str,
        catalog: AccountingReferenceCatalog,
        documents: list[dict[str, Any]] | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        clean_text = text.strip()
        if len(clean_text) < 4:
            raise ValueError("Persisted accounting model input is too short.")
        limit = max(1, min(int(top_k), 10))
        bundle = self.loader.load()
        identity = self.loader.identity()
        x = self._transform(bundle, self._model_text(clean_text, documents))
        tasks = bundle["tasks"]
        needs_retrieval = any(
            str(task.get("strategy") or "linear") in {"retrieval", "hybrid"}
            for task in tasks.values()
        )
        neighbors = similarities = None
        if needs_retrieval:
            train_matrix = bundle.get("retrieval_matrix")
            if train_matrix is None:
                raise PersistedAccountingModelError("Persisted bundle is missing its train-only retrieval matrix.")
            neighbors, similarities = self._neighbors(x, train_matrix, 5)

        resolver = _CatalogResolver(catalog)
        output: dict[str, Any] = {}
        for name in ("move_type", "journal"):
            output[name] = self._single_candidates(
                task_name=name,
                task=tasks[name],
                x=x,
                resolver=resolver,
                neighbors=neighbors,
                similarities=similarities,
                top_k=limit,
            )
        for name in ("debit_accounts", "credit_accounts", "taxes", "analytics"):
            output[name] = self._multi_candidates(
                task_name=name,
                task=tasks[name],
                x=x,
                resolver=resolver,
                neighbors=neighbors,
                similarities=similarities,
                top_k=limit,
            )

        critical_top_scores = [
            float(output[name][0]["model_score"])
            for name in ("move_type", "journal", "debit_accounts", "credit_accounts")
            if output.get(name)
        ]
        unresolved_selected = [
            candidate
            for name in ("journal", "debit_accounts", "credit_accounts")
            for candidate in output.get(name, [])
            if candidate.get("selected") and not candidate.get("live_reference_resolved")
        ]
        return {
            "model_version": identity.model_version,
            "bundle_sha256": identity.sha256,
            "bundle_verified": True,
            "input_contract": "attachment-derived text/features; no accounting target fields",
            "score_semantics": "ranking/model score; not a calibrated probability",
            "move_type": output["move_type"],
            "journals": output["journal"],
            "debit_accounts": output["debit_accounts"],
            "credit_accounts": output["credit_accounts"],
            "taxes": output["taxes"],
            "analytic_accounts": output["analytics"],
            "confidence_proxy": round(min(critical_top_scores), 6) if critical_top_scores else 0.0,
            "unresolved_selected_reference_count": len(unresolved_selected),
            "audit_safe": {
                "trained_during_request": False,
                "thresholds_tuned_during_request": False,
                "auto_posted_to_erp": False,
                "approval_required": True,
                "erp_access_mode": "read_only_reference_resolution",
            },
        }
