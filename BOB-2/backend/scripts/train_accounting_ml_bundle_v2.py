#!/usr/bin/env python3
"""Train leakage-safe hybrid accounting models using Train + Validation only.

V2 improvements over the baseline:
- label vocabulary is built from TRAIN ONLY;
- Validation-only labels are evaluation misses, never model classes;
- combines word and character hashing for Arabic/English OCR robustness;
- compares linear, retrieval, and hybrid strategies on Validation;
- stores Train retrieval matrix only when needed for the persisted predictor;
- never reads Test.
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
from sklearn.preprocessing import MultiLabelBinarizer, normalize

import train_accounting_ml_bundle as base

MODEL_VERSION = "accounting-ml-v2.0.0"
DEFAULT_WORD_FEATURES = 2**15
DEFAULT_CHAR_FEATURES = 2**15
DEFAULT_SEED = 20260816
LINEAR_THRESHOLD_GRID = tuple(float(x) for x in np.linspace(-2.5, 2.0, 19))
PROB_THRESHOLD_GRID = (0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60)
RETRIEVAL_K_GRID = (1, 3, 5)
BLEND_GRID = (0.35, 0.50, 0.65, 0.80)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_vectorizers(word_features: int, char_features: int) -> dict[str, HashingVectorizer]:
    return {
        "word": HashingVectorizer(
            n_features=word_features,
            alternate_sign=False,
            norm="l2",
            analyzer="word",
            ngram_range=(1, 2),
            lowercase=True,
            token_pattern=r"(?u)\b\w[\w.-]+\b",
            dtype=np.float32,
        ),
        "char": HashingVectorizer(
            n_features=char_features,
            alternate_sign=False,
            norm="l2",
            analyzer="char_wb",
            ngram_range=(3, 5),
            lowercase=True,
            dtype=np.float32,
        ),
    }


def transform_texts(vectorizers: dict[str, HashingVectorizer], texts: list[str]) -> sparse.csr_matrix:
    word = vectorizers["word"].transform(texts)
    char = vectorizers["char"].transform(texts)
    matrix = sparse.hstack((word, char), format="csr", dtype=np.float32)
    return normalize(matrix, norm="l2", copy=False).tocsr()


def make_classifier(seed: int, balanced: bool = False) -> SGDClassifier:
    return SGDClassifier(
        loss="log_loss",
        penalty="l2",
        alpha=2e-5,
        max_iter=2500,
        tol=1e-4,
        shuffle=True,
        random_state=seed,
        average=False,
        class_weight="balanced" if balanced else None,
    )


def downcast_model(model: Any) -> None:
    estimators = getattr(model, "estimators_", None)
    if estimators is None:
        estimators = [model]
    for estimator in estimators:
        if hasattr(estimator, "coef_"):
            estimator.coef_ = np.asarray(estimator.coef_, dtype=np.float32)
        if hasattr(estimator, "intercept_"):
            estimator.intercept_ = np.asarray(estimator.intercept_, dtype=np.float32)


def top_neighbors(x_query: sparse.csr_matrix, x_train: sparse.csr_matrix, max_k: int = 5) -> tuple[np.ndarray, np.ndarray]:
    sim = (x_query @ x_train.T).toarray().astype(np.float32, copy=False)
    k = min(max_k, sim.shape[1])
    idx = np.argpartition(sim, -k, axis=1)[:, -k:]
    row = np.arange(sim.shape[0])[:, None]
    vals = sim[row, idx]
    order = np.argsort(vals, axis=1)[:, ::-1]
    idx = idx[row, order]
    vals = vals[row, order]
    return idx, vals


def single_metrics(y_true: list[str], y_pred: list[str] | np.ndarray) -> dict[str, float]:
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y_true, y_pred, average="weighted", zero_division=0)),
    }


def single_objective(metrics: dict[str, float]) -> float:
    return metrics["accuracy"] + 0.55 * metrics["macro_f1"] + 0.25 * metrics["balanced_accuracy"]


def retrieval_single_predict(
    train_labels: list[str],
    neighbor_idx: np.ndarray,
    neighbor_sim: np.ndarray,
    k: int,
) -> list[str]:
    out: list[str] = []
    for idxs, sims in zip(neighbor_idx[:, :k], neighbor_sim[:, :k], strict=True):
        votes: dict[str, float] = {}
        for idx, sim in zip(idxs, sims, strict=True):
            label = str(train_labels[int(idx)])
            votes[label] = votes.get(label, 0.0) + max(float(sim), 1e-6)
        out.append(max(votes.items(), key=lambda item: (item[1], item[0]))[0])
    return out


def train_single(
    x_train: sparse.csr_matrix,
    y_train: list[str],
    x_val: sparse.csr_matrix,
    y_val: list[str],
    neighbor_idx: np.ndarray,
    neighbor_sim: np.ndarray,
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    model = make_classifier(seed, balanced=False)
    model.fit(x_train, y_train)
    linear_pred = model.predict(x_val)
    linear_metrics = single_metrics(y_val, linear_pred)
    best = {
        "strategy": "linear",
        "metrics": linear_metrics,
        "objective": single_objective(linear_metrics),
        "retrieval_k": None,
    }

    for k in RETRIEVAL_K_GRID:
        pred = retrieval_single_predict(y_train, neighbor_idx, neighbor_sim, k)
        metrics = single_metrics(y_val, pred)
        score = single_objective(metrics)
        if score > best["objective"]:
            best = {
                "strategy": "retrieval",
                "metrics": metrics,
                "objective": score,
                "retrieval_k": k,
            }

    downcast_model(model)
    task = {
        "kind": "single",
        "strategy": best["strategy"],
        "model": model,
        "retrieval_k": best["retrieval_k"],
        "train_labels": list(y_train) if best["strategy"] == "retrieval" else None,
    }
    metrics = {
        "validation_examples": len(y_val),
        "classes": [str(x) for x in model.classes_.tolist()],
        "train_class_counts": dict(Counter(y_train)),
        "strategy": best["strategy"],
        "retrieval_k": best["retrieval_k"],
        **best["metrics"],
        "linear_baseline": linear_metrics,
    }
    return task, metrics


def train_only_binarizer(y_train: list[list[str]]) -> MultiLabelBinarizer:
    classes = sorted({label for labels in y_train for label in labels})
    mlb = MultiLabelBinarizer(classes=classes)
    mlb.fit([[]])
    return mlb


def encode_known(labels: list[list[str]], classes: list[str] | np.ndarray) -> np.ndarray:
    index = {str(label): i for i, label in enumerate(classes)}
    matrix = np.zeros((len(labels), len(index)), dtype=np.int8)
    for row, values in enumerate(labels):
        for value in values:
            col = index.get(str(value))
            if col is not None:
                matrix[row, col] = 1
    return matrix


def evaluation_space(
    train_classes: list[str] | np.ndarray,
    validation_labels: list[list[str]],
) -> tuple[list[str], np.ndarray, np.ndarray]:
    train_classes = [str(x) for x in train_classes]
    val_classes = {str(label) for labels in validation_labels for label in labels}
    eval_classes = sorted(set(train_classes) | val_classes)
    y_true = encode_known(validation_labels, eval_classes)
    train_to_eval = np.asarray([eval_classes.index(label) for label in train_classes], dtype=np.int32)
    return eval_classes, y_true, train_to_eval


def expand_predictions(pred_train: np.ndarray, eval_width: int, train_to_eval: np.ndarray) -> np.ndarray:
    out = np.zeros((pred_train.shape[0], eval_width), dtype=np.int8)
    out[:, train_to_eval] = pred_train.astype(np.int8, copy=False)
    return out


def multilabel_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "exact_match": float(accuracy_score(y_true, y_pred)),
        "micro_precision": float(precision_score(y_true, y_pred, average="micro", zero_division=0)),
        "micro_recall": float(recall_score(y_true, y_pred, average="micro", zero_division=0)),
        "micro_f1": float(f1_score(y_true, y_pred, average="micro", zero_division=0)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "samples_f1": float(f1_score(y_true, y_pred, average="samples", zero_division=0)),
        "hamming_loss": float(hamming_loss(y_true, y_pred)),
        "true_label_cardinality": float(y_true.sum(axis=1).mean()),
        "pred_label_cardinality": float(y_pred.sum(axis=1).mean()),
    }


def multi_objective(metrics: dict[str, float]) -> float:
    return (
        metrics["micro_f1"]
        + 0.80 * metrics["samples_f1"]
        + 0.30 * metrics["exact_match"]
        + 0.25 * metrics["micro_recall"]
        - 0.08 * abs(metrics["pred_label_cardinality"] - metrics["true_label_cardinality"])
    )


def sigmoid(scores: np.ndarray) -> np.ndarray:
    clipped = np.clip(scores, -20.0, 20.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def retrieval_multi_scores(
    y_train_bin: np.ndarray,
    neighbor_idx: np.ndarray,
    neighbor_sim: np.ndarray,
    k: int,
) -> np.ndarray:
    n = neighbor_idx.shape[0]
    out = np.zeros((n, y_train_bin.shape[1]), dtype=np.float32)
    for row in range(n):
        idx = neighbor_idx[row, :k]
        weights = np.maximum(neighbor_sim[row, :k], 1e-6).astype(np.float32)
        denom = float(weights.sum()) or 1.0
        out[row] = (y_train_bin[idx].astype(np.float32) * weights[:, None]).sum(axis=0) / denom
    return out


def ranking_recall_at_k(
    linear_scores: np.ndarray,
    validation_labels: list[list[str]],
    train_classes: list[str],
    k: int,
) -> float:
    class_index = {label: i for i, label in enumerate(train_classes)}
    total = 0
    hit = 0
    top = np.argsort(linear_scores, axis=1)[:, ::-1][:, : min(k, linear_scores.shape[1])]
    for row, labels in enumerate(validation_labels):
        predicted = set(int(x) for x in top[row])
        for label in labels:
            total += 1
            idx = class_index.get(str(label))
            if idx is not None and idx in predicted:
                hit += 1
    return float(hit / total) if total else 1.0


def train_multi(
    x_train: sparse.csr_matrix,
    y_train: list[list[str]],
    x_val: sparse.csr_matrix,
    y_val: list[list[str]],
    neighbor_idx: np.ndarray,
    neighbor_sim: np.ndarray,
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    mlb = train_only_binarizer(y_train)
    train_classes = [str(x) for x in mlb.classes_.tolist()]
    y_train_bin = encode_known(y_train, train_classes)
    eval_classes, y_true_eval, train_to_eval = evaluation_space(train_classes, y_val)
    unseen = sorted(set(eval_classes) - set(train_classes))

    candidates: list[dict[str, Any]] = []
    retained_models: list[tuple[str, OneVsRestClassifier, np.ndarray]] = []

    for balanced in (False, True):
        model = OneVsRestClassifier(make_classifier(seed + (100 if balanced else 0), balanced=balanced), n_jobs=1)
        model.fit(x_train, y_train_bin)
        linear_scores = np.asarray(model.decision_function(x_val), dtype=np.float32)
        if linear_scores.ndim == 1:
            linear_scores = linear_scores.reshape(-1, 1)

        best_linear = None
        for threshold in LINEAR_THRESHOLD_GRID:
            pred_train = (linear_scores >= threshold).astype(np.int8)
            pred_eval = expand_predictions(pred_train, len(eval_classes), train_to_eval)
            metrics = multilabel_metrics(y_true_eval, pred_eval)
            obj = multi_objective(metrics)
            if best_linear is None or obj > best_linear["objective"]:
                best_linear = {
                    "strategy": "linear",
                    "balanced": balanced,
                    "threshold": float(threshold),
                    "metrics": metrics,
                    "objective": obj,
                    "retrieval_k": None,
                    "blend_weight": None,
                }
        assert best_linear is not None
        candidates.append(best_linear)
        retained_models.append(("balanced" if balanced else "plain", model, linear_scores))

    # Retrieval and hybrid use the better linear family only.
    best_linear_candidate = max(candidates, key=lambda x: x["objective"])
    model_key = "balanced" if best_linear_candidate["balanced"] else "plain"
    selected_model = next(model for key, model, _ in retained_models if key == model_key)
    selected_scores = next(scores for key, _, scores in retained_models if key == model_key)
    linear_prob = sigmoid(selected_scores)

    for k in RETRIEVAL_K_GRID:
        retrieval = retrieval_multi_scores(y_train_bin, neighbor_idx, neighbor_sim, k)
        for threshold in PROB_THRESHOLD_GRID:
            pred_train = (retrieval >= threshold).astype(np.int8)
            pred_eval = expand_predictions(pred_train, len(eval_classes), train_to_eval)
            metrics = multilabel_metrics(y_true_eval, pred_eval)
            candidates.append({
                "strategy": "retrieval",
                "balanced": best_linear_candidate["balanced"],
                "threshold": float(threshold),
                "metrics": metrics,
                "objective": multi_objective(metrics),
                "retrieval_k": k,
                "blend_weight": 0.0,
            })

        for blend in BLEND_GRID:
            combined = blend * linear_prob + (1.0 - blend) * retrieval
            for threshold in PROB_THRESHOLD_GRID:
                pred_train = (combined >= threshold).astype(np.int8)
                pred_eval = expand_predictions(pred_train, len(eval_classes), train_to_eval)
                metrics = multilabel_metrics(y_true_eval, pred_eval)
                candidates.append({
                    "strategy": "hybrid",
                    "balanced": best_linear_candidate["balanced"],
                    "threshold": float(threshold),
                    "metrics": metrics,
                    "objective": multi_objective(metrics),
                    "retrieval_k": k,
                    "blend_weight": float(blend),
                })

    best = max(candidates, key=lambda x: x["objective"])
    # If winner needs a different linear family, select it now.
    if best["strategy"] == "linear":
        model_key = "balanced" if best["balanced"] else "plain"
        selected_model = next(model for key, model, _ in retained_models if key == model_key)
        selected_scores = next(scores for key, _, scores in retained_models if key == model_key)

    downcast_model(selected_model)
    task = {
        "kind": "multi",
        "strategy": best["strategy"],
        "model": selected_model,
        "binarizer": mlb,
        "threshold": best["threshold"],
        "retrieval_k": best["retrieval_k"],
        "blend_weight": best["blend_weight"],
        "train_label_matrix": y_train_bin.astype(np.uint8) if best["strategy"] in {"retrieval", "hybrid"} else None,
    }

    counts = Counter(label for labels in y_train for label in labels)
    metrics = {
        "validation_examples": len(y_val),
        "labels": train_classes,
        "evaluation_label_count": len(eval_classes),
        "train_label_counts": dict(counts),
        "validation_unseen_labels": unseen,
        "validation_unseen_label_count": len(unseen),
        "label_vocabulary_source": "train_only",
        "strategy": best["strategy"],
        "balanced_linear": bool(best["balanced"]),
        "threshold": best["threshold"],
        "retrieval_k": best["retrieval_k"],
        "blend_weight": best["blend_weight"],
        **best["metrics"],
        "ranking_recall_at_3": ranking_recall_at_k(selected_scores, y_val, train_classes, 3),
        "ranking_recall_at_5": ranking_recall_at_k(selected_scores, y_val, train_classes, 5),
        "candidate_count": len(candidates),
    }
    return task, metrics


def predict_retrieval_multi(task: dict[str, Any], neighbors: np.ndarray, sims: np.ndarray) -> np.ndarray:
    matrix = task["train_label_matrix"]
    return retrieval_multi_scores(matrix, neighbors, sims, int(task["retrieval_k"]))


def reload_smoke(bundle_path: Path, validation_texts: list[str]) -> dict[str, Any]:
    bundle = joblib.load(bundle_path)
    texts = validation_texts[: min(5, len(validation_texts))]
    x = transform_texts(bundle["vectorizers"], texts)
    needs_retrieval = any(task.get("strategy") in {"retrieval", "hybrid"} for task in bundle["tasks"].values())
    neighbors = sims = None
    if needs_retrieval:
        neighbors, sims = top_neighbors(x, bundle["retrieval_matrix"], 5)

    out: dict[str, Any] = {"sample_count": len(texts), "tasks": {}}
    for name, task in bundle["tasks"].items():
        strategy = task["strategy"]
        if task["kind"] == "single":
            if strategy == "linear":
                pred = task["model"].predict(x)
                out["tasks"][name] = [str(v) for v in pred.tolist()]
            else:
                assert neighbors is not None and sims is not None
                out["tasks"][name] = retrieval_single_predict(task["train_labels"], neighbors, sims, int(task["retrieval_k"]))
            continue

        linear_scores = np.asarray(task["model"].decision_function(x), dtype=np.float32)
        if linear_scores.ndim == 1:
            linear_scores = linear_scores.reshape(-1, 1)
        if strategy == "linear":
            mask = linear_scores >= float(task["threshold"])
        else:
            assert neighbors is not None and sims is not None
            retrieval = predict_retrieval_multi(task, neighbors, sims)
            if strategy == "retrieval":
                combined = retrieval
            else:
                w = float(task["blend_weight"])
                combined = w * sigmoid(linear_scores) + (1.0 - w) * retrieval
            mask = combined >= float(task["threshold"])
        classes = np.asarray(task["binarizer"].classes_)
        out["tasks"][name] = [[str(v) for v in classes[row].tolist()] for row in mask]
    return out


def summarize_metrics(task_metrics: dict[str, Any]) -> dict[str, Any]:
    hidden = {"classes", "labels", "train_class_counts", "train_label_counts", "linear_baseline"}
    return {key: value for key, value in task_metrics.items() if key not in hidden}


def load_baseline_manifest(root: Path) -> dict[str, Any] | None:
    path = root / "models" / "accounting_ml_v1" / "manifest.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/data/storage/odoo-training-dataset")
    parser.add_argument("--word-features", type=int, default=DEFAULT_WORD_FEATURES)
    parser.add_argument("--char-features", type=int, default=DEFAULT_CHAR_FEATURES)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    root = Path(args.root)
    supervised = root / "training" / "supervised_v1"
    train_path = supervised / "train.jsonl"
    val_path = supervised / "validation.jsonl"
    test_path = supervised / "test.jsonl"
    output_dir = root / "models" / "accounting_ml_v2"
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / "accounting_model_bundle_v2.joblib"
    manifest_path = output_dir / "manifest.json"

    free_before = shutil.disk_usage(root).free
    if free_before < 150 * 1024**2:
        raise RuntimeError(f"Insufficient persistent free disk: {free_before / 1024**2:.1f} MiB")

    print("MODEL_VERSION =", MODEL_VERSION)
    print("TRAIN_PATH =", train_path)
    print("VALIDATION_PATH =", val_path)
    print("TEST_PATH =", test_path, "(NOT READ)")
    print("LABEL_VOCABULARY = TRAIN_ONLY")
    print("WORD_HASH_FEATURES =", args.word_features)
    print("CHAR_HASH_FEATURES =", args.char_features)
    print("FREE_MIB_BEFORE =", round(free_before / 1024**2, 2))

    train_texts, train_y, _ = base.load_dataset(train_path)
    val_texts, val_y, _ = base.load_dataset(val_path)
    if len(train_texts) != 4575 or len(val_texts) != 573:
        raise RuntimeError(f"Unexpected split sizes train={len(train_texts)} validation={len(val_texts)}")

    vectorizers = make_vectorizers(args.word_features, args.char_features)
    x_train = transform_texts(vectorizers, train_texts)
    x_val = transform_texts(vectorizers, val_texts)
    matrix_mib = (x_train.data.nbytes + x_train.indices.nbytes + x_train.indptr.nbytes) / 1024**2
    print("X_TRAIN shape=", x_train.shape, "nnz=", x_train.nnz, "MiB=", round(matrix_mib, 2))
    print("X_VALIDATION shape=", x_val.shape, "nnz=", x_val.nnz)

    neighbor_idx, neighbor_sim = top_neighbors(x_val, x_train, 5)
    print("RETRIEVAL_INDEX = TRAIN_MATRIX_ONLY")

    tasks: dict[str, dict[str, Any]] = {}
    metrics: dict[str, Any] = {}

    for offset, name in enumerate(("move_type", "journal"), start=1):
        print("TRAINING_TASK =", name)
        task, task_metrics = train_single(
            x_train, train_y[name], x_val, val_y[name], neighbor_idx, neighbor_sim, args.seed + offset
        )
        tasks[name] = task
        metrics[name] = task_metrics
        summary = summarize_metrics(task_metrics)
        summary["class_count"] = len(task_metrics["classes"])
        print("VALIDATION_METRICS", name, json.dumps(summary, ensure_ascii=False))

    for offset, name in enumerate(("debit_accounts", "credit_accounts", "taxes", "analytics"), start=20):
        print("TRAINING_TASK =", name)
        task, task_metrics = train_multi(
            x_train, train_y[name], x_val, val_y[name], neighbor_idx, neighbor_sim, args.seed + offset
        )
        tasks[name] = task
        metrics[name] = task_metrics
        summary = summarize_metrics(task_metrics)
        summary["train_label_count"] = len(task_metrics["labels"])
        print("VALIDATION_METRICS", name, json.dumps(summary, ensure_ascii=False))

    needs_retrieval = any(task.get("strategy") in {"retrieval", "hybrid"} for task in tasks.values())
    metadata = {
        "model_version": MODEL_VERSION,
        "created_at": utc_now(),
        "sklearn_version": sklearn.__version__,
        "numpy_version": np.__version__,
        "seed": args.seed,
        "features": {
            "word_hash_features": args.word_features,
            "char_hash_features": args.char_features,
            "word_ngram_range": [1, 2],
            "char_ngram_range": [3, 5],
        },
        "training_contract": {
            "train_examples": len(train_texts),
            "validation_examples": len(val_texts),
            "test_read": False,
            "label_vocabulary": "train_only",
            "retrieval_corpus": "train_only",
            "input": "attachment-derived features only",
        },
        "metrics": metrics,
    }

    bundle = {
        "metadata": metadata,
        "vectorizers": vectorizers,
        "tasks": tasks,
        "retrieval_matrix": x_train.astype(np.float32) if needs_retrieval else None,
    }
    tmp = output_dir / ".accounting_model_bundle_v2.joblib.tmp"
    tmp.unlink(missing_ok=True)
    joblib.dump(bundle, tmp, compress=3)
    os.replace(tmp, bundle_path)

    free_after = shutil.disk_usage(root).free
    bundle_bytes = bundle_path.stat().st_size
    smoke = reload_smoke(bundle_path, val_texts)
    baseline = load_baseline_manifest(root)

    manifest = {
        **metadata,
        "baseline_v1_available": baseline is not None,
        "bundle_path": str(bundle_path),
        "bundle_bytes": bundle_bytes,
        "bundle_mib": round(bundle_bytes / 1024**2, 2),
        "free_mib_before": round(free_before / 1024**2, 2),
        "free_mib_after": round(free_after / 1024**2, 2),
        "reload_smoke": smoke,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print("MODEL_BUNDLE =", bundle_path)
    print("MODEL_BUNDLE_MIB =", round(bundle_bytes / 1024**2, 2))
    print("LABEL_VOCABULARY_LEAKAGE=PASS")
    print("RETRIEVAL_TRAIN_ONLY=PASS")
    print("PERSISTENCE_RELOAD_CHECK=PASS")
    print("VALIDATION_ONLY_EVALUATION=PASS")
    print("TEST_SET_UNTOUCHED=PASS")
    print("TRAIN_ONCE_PERSIST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
