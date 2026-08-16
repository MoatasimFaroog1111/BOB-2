#!/usr/bin/env python3
"""Train and persist a lightweight accounting classification bundle.

Discipline:
- trains on supervised_v1/train.jsonl only;
- chooses multi-label thresholds on validation.jsonl only;
- never reads test.jsonl;
- uses attachment-derived input features only;
- persists a reloadable bundle for Train Once -> Load & Predict.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import sklearn
from scipy import sparse
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    f1_score,
    hamming_loss,
    precision_score,
    recall_score,
)
from sklearn.multiclass import OneVsRestClassifier
from sklearn.preprocessing import MultiLabelBinarizer

MODEL_VERSION = "accounting-ml-v1.0.0"
DEFAULT_HASH_FEATURES = 2**16
DEFAULT_SEED = 20260816
THRESHOLD_GRID = tuple(float(x) for x in np.linspace(-2.5, 2.5, 21))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_ident(obj: Any) -> str | None:
    if not isinstance(obj, dict):
        return None
    value = obj.get("code") or obj.get("name") or obj.get("id")
    return str(value) if value not in (None, False, "") else None


def model_text(row: dict[str, Any]) -> str:
    inp = row.get("input", {})
    documents = inp.get("documents") or []
    tags: list[str] = [f"__doc_count_{min(len(documents), 10)}"]

    has_ocr = False
    for doc in documents:
        extractor = str(doc.get("extractor") or "unknown").lower()
        ext = str(doc.get("extension") or "none").lower().lstrip(".")
        mime = str(doc.get("mime") or "unknown").lower().replace("/", "_")
        tags.append(f"__extractor_{extractor}")
        tags.append(f"__ext_{ext}")
        tags.append(f"__mime_{mime}")
        if int(doc.get("ocr_pages") or 0) > 0:
            has_ocr = True

    tags.append("__has_ocr" if has_ocr else "__no_ocr")
    return " ".join(tags) + "\n" + str(inp.get("combined_text") or "")


def extract_labels(row: dict[str, Any]) -> dict[str, Any]:
    target = row.get("target", {})
    move = target.get("move", {})
    labels = target.get("labels", {})

    journal = stable_ident(move.get("journal")) or "UNKNOWN"

    def multi(items: Any) -> list[str]:
        values: list[str] = []
        for item in items or []:
            value = stable_ident(item)
            if value is not None:
                values.append(value)
        return sorted(set(values))

    return {
        "move_type": str(move.get("move_type") or "UNKNOWN"),
        "journal": journal,
        "debit_accounts": multi(labels.get("debit_accounts")),
        "credit_accounts": multi(labels.get("credit_accounts")),
        "taxes": multi(labels.get("taxes")),
        "analytics": multi(labels.get("analytic_accounts")),
    }


def load_dataset(path: Path) -> tuple[list[str], dict[str, list[Any]], list[str]]:
    texts: list[str] = []
    ids: list[str] = []
    y: dict[str, list[Any]] = {
        "move_type": [],
        "journal": [],
        "debit_accounts": [],
        "credit_accounts": [],
        "taxes": [],
        "analytics": [],
    }

    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            ids.append(str(row.get("example_id")))
            texts.append(model_text(row))
            labels = extract_labels(row)
            for key in y:
                y[key].append(labels[key])

    return texts, y, ids


def make_vectorizer(n_features: int) -> HashingVectorizer:
    return HashingVectorizer(
        n_features=n_features,
        alternate_sign=False,
        norm="l2",
        analyzer="word",
        ngram_range=(1, 2),
        lowercase=True,
        token_pattern=r"(?u)\b\w[\w.-]+\b",
        dtype=np.float32,
    )


def make_classifier(seed: int) -> SGDClassifier:
    return SGDClassifier(
        loss="log_loss",
        penalty="l2",
        alpha=2e-5,
        max_iter=2000,
        tol=1e-4,
        shuffle=True,
        random_state=seed,
        average=False,
    )


def train_single(
    x_train: sparse.spmatrix,
    y_train: list[str],
    x_validation: sparse.spmatrix,
    y_validation: list[str],
    seed: int,
) -> tuple[SGDClassifier, dict[str, Any]]:
    model = make_classifier(seed)
    model.fit(x_train, y_train)
    pred = model.predict(x_validation)

    metrics = {
        "validation_examples": len(y_validation),
        "classes": [str(x) for x in model.classes_.tolist()],
        "train_class_counts": dict(Counter(y_train)),
        "validation_accuracy": float(accuracy_score(y_validation, pred)),
        "validation_balanced_accuracy": float(
            balanced_accuracy_score(y_validation, pred)
        ),
        "validation_macro_f1": float(
            f1_score(y_validation, pred, average="macro", zero_division=0)
        ),
        "validation_weighted_f1": float(
            f1_score(y_validation, pred, average="weighted", zero_division=0)
        ),
    }
    return model, metrics


def decision_matrix(model: OneVsRestClassifier, x: sparse.spmatrix) -> np.ndarray:
    scores = np.asarray(model.decision_function(x))
    if scores.ndim == 1:
        scores = scores.reshape(-1, 1)
    return scores


def multilabel_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "exact_match": float(accuracy_score(y_true, y_pred)),
        "micro_precision": float(
            precision_score(y_true, y_pred, average="micro", zero_division=0)
        ),
        "micro_recall": float(
            recall_score(y_true, y_pred, average="micro", zero_division=0)
        ),
        "micro_f1": float(
            f1_score(y_true, y_pred, average="micro", zero_division=0)
        ),
        "macro_f1": float(
            f1_score(y_true, y_pred, average="macro", zero_division=0)
        ),
        "samples_f1": float(
            f1_score(y_true, y_pred, average="samples", zero_division=0)
        ),
        "hamming_loss": float(hamming_loss(y_true, y_pred)),
        "true_label_cardinality": float(np.asarray(y_true).sum(axis=1).mean()),
        "pred_label_cardinality": float(np.asarray(y_pred).sum(axis=1).mean()),
    }


def choose_threshold(
    scores: np.ndarray,
    y_true: np.ndarray,
) -> tuple[float, dict[str, float]]:
    best_threshold = 0.0
    best_metrics: dict[str, float] | None = None
    best_score = -math.inf

    for threshold in THRESHOLD_GRID:
        pred = (scores >= threshold).astype(np.int8)
        metrics = multilabel_metrics(y_true, pred)
        objective = (
            metrics["samples_f1"]
            + metrics["micro_f1"]
            + 0.50 * metrics["exact_match"]
            - 0.10
            * abs(
                metrics["pred_label_cardinality"]
                - metrics["true_label_cardinality"]
            )
        )
        if objective > best_score:
            best_score = objective
            best_threshold = float(threshold)
            best_metrics = metrics

    assert best_metrics is not None
    return best_threshold, best_metrics


def train_multi(
    x_train: sparse.spmatrix,
    y_train: list[list[str]],
    x_validation: sparse.spmatrix,
    y_validation: list[list[str]],
    seed: int,
) -> tuple[
    OneVsRestClassifier,
    MultiLabelBinarizer,
    float,
    dict[str, Any],
]:
    train_labels = {label for labels in y_train for label in labels}
    validation_labels = {label for labels in y_validation for label in labels}
    all_classes = sorted(train_labels | validation_labels)

    mlb = MultiLabelBinarizer(classes=all_classes)
    y_train_bin = mlb.fit_transform(y_train)
    y_validation_bin = mlb.transform(y_validation)

    model = OneVsRestClassifier(make_classifier(seed), n_jobs=1)
    model.fit(x_train, y_train_bin)

    scores = decision_matrix(model, x_validation)
    threshold, validation_metrics = choose_threshold(scores, y_validation_bin)

    counts = Counter(label for labels in y_train for label in labels)
    unseen = sorted(validation_labels - train_labels)
    metrics: dict[str, Any] = {
        "validation_examples": len(y_validation),
        "labels": [str(x) for x in mlb.classes_.tolist()],
        "train_label_counts": dict(counts),
        "validation_unseen_labels": unseen,
        "threshold": threshold,
        **validation_metrics,
    }
    return model, mlb, threshold, metrics


def downcast_model(model: Any) -> None:
    estimators = getattr(model, "estimators_", None)
    if estimators is None:
        estimators = [model]

    for estimator in estimators:
        if hasattr(estimator, "coef_"):
            estimator.coef_ = np.asarray(estimator.coef_, dtype=np.float32)
        if hasattr(estimator, "intercept_"):
            estimator.intercept_ = np.asarray(
                estimator.intercept_,
                dtype=np.float32,
            )


def bundle_reload_smoke(
    bundle_path: Path,
    validation_texts: list[str],
) -> dict[str, Any]:
    bundle = joblib.load(bundle_path)
    vectorizer = bundle["vectorizer"]
    sample_texts = validation_texts[: min(5, len(validation_texts))]
    x = vectorizer.transform(sample_texts)

    smoke: dict[str, Any] = {
        "sample_count": len(sample_texts),
        "tasks": {},
    }
    for name, task in bundle["tasks"].items():
        model = task["model"]
        if task["kind"] == "single":
            pred = model.predict(x)
            smoke["tasks"][name] = [str(v) for v in pred.tolist()]
        else:
            scores = decision_matrix(model, x)
            mask = scores >= float(task["threshold"])
            classes = np.asarray(task["binarizer"].classes_)
            decoded = [
                [str(v) for v in classes[row_mask].tolist()]
                for row_mask in mask
            ]
            smoke["tasks"][name] = decoded
    return smoke


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        default="/data/storage/odoo-training-dataset",
    )
    parser.add_argument(
        "--hash-features",
        type=int,
        default=DEFAULT_HASH_FEATURES,
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.root)
    supervised = root / "training" / "supervised_v1"
    train_path = supervised / "train.jsonl"
    validation_path = supervised / "validation.jsonl"
    test_path = supervised / "test.jsonl"

    if not train_path.is_file() or not validation_path.is_file():
        raise FileNotFoundError("train.jsonl or validation.jsonl is missing")

    output_dir = root / "models" / "accounting_ml_v1"
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / "accounting_model_bundle.joblib"
    manifest_path = output_dir / "manifest.json"

    free_before = shutil.disk_usage(root).free
    if free_before < 150 * 1024**2:
        raise RuntimeError(
            "Insufficient persistent free disk before training: "
            f"{free_before / 1024**2:.1f} MiB"
        )

    print("MODEL_VERSION =", MODEL_VERSION)
    print("TRAIN_PATH =", train_path)
    print("VALIDATION_PATH =", validation_path)
    print("TEST_PATH =", test_path, "(NOT READ)")
    print("HASH_FEATURES =", args.hash_features)
    print("FREE_MIB_BEFORE =", round(free_before / 1024**2, 2))

    train_texts, train_y, _ = load_dataset(train_path)
    validation_texts, validation_y, _ = load_dataset(validation_path)

    if len(train_texts) != 4575:
        raise RuntimeError(f"Unexpected train count: {len(train_texts)}")
    if len(validation_texts) != 573:
        raise RuntimeError(
            f"Unexpected validation count: {len(validation_texts)}"
        )

    vectorizer = make_vectorizer(args.hash_features)
    x_train = vectorizer.transform(train_texts)
    x_validation = vectorizer.transform(validation_texts)

    train_matrix_mib = (
        x_train.data.nbytes
        + x_train.indices.nbytes
        + x_train.indptr.nbytes
    ) / 1024**2
    print(
        "X_TRAIN shape=",
        x_train.shape,
        "nnz=",
        x_train.nnz,
        "MiB=",
        round(train_matrix_mib, 2),
    )
    print(
        "X_VALIDATION shape=",
        x_validation.shape,
        "nnz=",
        x_validation.nnz,
    )

    tasks: dict[str, dict[str, Any]] = {}
    metrics: dict[str, Any] = {}

    for offset, name in enumerate(
        ("move_type", "journal"),
        start=1,
    ):
        print("TRAINING_TASK =", name)
        model, task_metrics = train_single(
            x_train,
            train_y[name],
            x_validation,
            validation_y[name],
            args.seed + offset,
        )
        downcast_model(model)
        tasks[name] = {
            "kind": "single",
            "model": model,
        }
        metrics[name] = task_metrics
        summary = {
            key: value
            for key, value in task_metrics.items()
            if key not in {"classes", "train_class_counts"}
        }
        summary["class_count"] = len(task_metrics["classes"])
        print(
            "VALIDATION_METRICS",
            name,
            json.dumps(summary, ensure_ascii=False),
        )

    for offset, name in enumerate(
        (
            "debit_accounts",
            "credit_accounts",
            "taxes",
            "analytics",
        ),
        start=20,
    ):
        print("TRAINING_TASK =", name)
        model, mlb, threshold, task_metrics = train_multi(
            x_train,
            train_y[name],
            x_validation,
            validation_y[name],
            args.seed + offset,
        )
        downcast_model(model)
        tasks[name] = {
            "kind": "multi",
            "model": model,
            "binarizer": mlb,
            "threshold": threshold,
        }
        metrics[name] = task_metrics
        summary = {
            key: value
            for key, value in task_metrics.items()
            if key not in {"labels", "train_label_counts"}
        }
        summary["label_count"] = len(task_metrics["labels"])
        print(
            "VALIDATION_METRICS",
            name,
            json.dumps(summary, ensure_ascii=False),
        )

    metadata = {
        "model_version": MODEL_VERSION,
        "created_at": utc_now(),
        "sklearn_version": sklearn.__version__,
        "numpy_version": np.__version__,
        "seed": args.seed,
        "hash_features": args.hash_features,
        "text_vectorizer": {
            "type": "HashingVectorizer",
            "analyzer": "word",
            "ngram_range": [1, 2],
            "alternate_sign": False,
            "dtype": "float32",
        },
        "training_contract": {
            "train_examples": len(train_texts),
            "validation_examples": len(validation_texts),
            "test_read": False,
            "input": "attachment-derived features only",
        },
        "metrics": metrics,
    }

    bundle = {
        "metadata": metadata,
        "vectorizer": vectorizer,
        "tasks": tasks,
    }

    tmp_path = output_dir / ".accounting_model_bundle.joblib.tmp"
    if tmp_path.exists():
        tmp_path.unlink()
    joblib.dump(bundle, tmp_path, compress=3)
    os.replace(tmp_path, bundle_path)

    bundle_bytes = bundle_path.stat().st_size
    free_after = shutil.disk_usage(root).free
    reload_smoke = bundle_reload_smoke(
        bundle_path,
        validation_texts,
    )

    manifest = {
        **metadata,
        "bundle_path": str(bundle_path),
        "bundle_bytes": bundle_bytes,
        "bundle_mib": round(bundle_bytes / 1024**2, 2),
        "free_mib_before": round(free_before / 1024**2, 2),
        "free_mib_after": round(free_after / 1024**2, 2),
        "reload_smoke": reload_smoke,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print("MODEL_BUNDLE =", bundle_path)
    print(
        "MODEL_BUNDLE_MIB =",
        round(bundle_bytes / 1024**2, 2),
    )
    print("PERSISTENCE_RELOAD_CHECK=PASS")
    print("VALIDATION_ONLY_EVALUATION=PASS")
    print("TEST_SET_UNTOUCHED=PASS")
    print("TRAIN_ONCE_PERSIST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
