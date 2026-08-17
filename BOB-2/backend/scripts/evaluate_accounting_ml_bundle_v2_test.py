#!/usr/bin/env python3
"""Evaluate the persisted accounting ML v2 bundle on Test exactly once.

Rules:
- loads an already-trained persisted bundle; never retrains;
- never changes thresholds, strategies, features, or label vocabulary;
- reads test.jsonl only for this final evaluation;
- evaluates validation-unseen/test-unseen labels as misses without adding them to model classes;
- writes a small immutable-style test report and refuses normal repeat execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np

import train_accounting_ml_bundle as base
import train_accounting_ml_bundle_v2 as v2

EXPECTED_TEST_EXAMPLES = 571
REPORT_SCHEMA = "accounting-ml-v2-test-evaluation-v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def label_set(rows: list[list[str]]) -> set[str]:
    return {str(label) for labels in rows for label in labels}


def predict_single(
    task: dict[str, Any],
    x_test: Any,
    neighbor_idx: np.ndarray | None,
    neighbor_sim: np.ndarray | None,
) -> list[str]:
    strategy = str(task["strategy"])
    if strategy == "linear":
        return [str(v) for v in task["model"].predict(x_test).tolist()]

    if strategy != "retrieval":
        raise RuntimeError(f"Unsupported single-label strategy: {strategy}")
    if neighbor_idx is None or neighbor_sim is None:
        raise RuntimeError("Retrieval neighbors are unavailable")

    return v2.retrieval_single_predict(
        task["train_labels"],
        neighbor_idx,
        neighbor_sim,
        int(task["retrieval_k"]),
    )


def predict_multi(
    task: dict[str, Any],
    x_test: Any,
    neighbor_idx: np.ndarray | None,
    neighbor_sim: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray]:
    linear_scores = np.asarray(
        task["model"].decision_function(x_test),
        dtype=np.float32,
    )
    if linear_scores.ndim == 1:
        linear_scores = linear_scores.reshape(-1, 1)

    strategy = str(task["strategy"])
    threshold = float(task["threshold"])

    if strategy == "linear":
        return (linear_scores >= threshold).astype(np.int8), linear_scores

    if neighbor_idx is None or neighbor_sim is None:
        raise RuntimeError("Retrieval neighbors are unavailable")

    retrieval = v2.predict_retrieval_multi(task, neighbor_idx, neighbor_sim)
    if strategy == "retrieval":
        combined = retrieval
    elif strategy == "hybrid":
        weight = float(task["blend_weight"])
        combined = weight * v2.sigmoid(linear_scores) + (1.0 - weight) * retrieval
    else:
        raise RuntimeError(f"Unsupported multi-label strategy: {strategy}")

    return (combined >= threshold).astype(np.int8), linear_scores


def multi_test_metrics(
    task: dict[str, Any],
    y_test: list[list[str]],
    pred_train_space: np.ndarray,
    linear_scores: np.ndarray,
) -> dict[str, Any]:
    train_classes = [str(v) for v in task["binarizer"].classes_.tolist()]
    test_classes = label_set(y_test)
    eval_classes = sorted(set(train_classes) | test_classes)
    y_true = v2.encode_known(y_test, eval_classes)
    train_to_eval = np.asarray(
        [eval_classes.index(label) for label in train_classes],
        dtype=np.int32,
    )
    y_pred = v2.expand_predictions(
        pred_train_space,
        len(eval_classes),
        train_to_eval,
    )
    metrics = v2.multilabel_metrics(y_true, y_pred)
    unseen = sorted(test_classes - set(train_classes))
    return {
        "test_examples": len(y_test),
        "strategy": task["strategy"],
        "threshold_locked_from_validation": float(task["threshold"]),
        "retrieval_k_locked_from_validation": task.get("retrieval_k"),
        "blend_weight_locked_from_validation": task.get("blend_weight"),
        "train_label_count": len(train_classes),
        "evaluation_label_count": len(eval_classes),
        "test_unseen_labels": unseen,
        "test_unseen_label_count": len(unseen),
        **metrics,
        "ranking_recall_at_3": v2.ranking_recall_at_k(
            linear_scores,
            y_test,
            train_classes,
            3,
        ),
        "ranking_recall_at_5": v2.ranking_recall_at_k(
            linear_scores,
            y_test,
            train_classes,
            5,
        ),
    }


def validation_reference(bundle: dict[str, Any], task_name: str) -> dict[str, Any]:
    return dict(
        bundle.get("metadata", {})
        .get("metrics", {})
        .get(task_name, {})
    )


def primary_metric(task_name: str, metrics: dict[str, Any]) -> tuple[str, float]:
    if task_name in {"move_type", "journal"}:
        return "accuracy", float(metrics.get("accuracy", 0.0))
    return "micro_f1", float(metrics.get("micro_f1", 0.0))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        default="/data/storage/odoo-training-dataset",
    )
    args = parser.parse_args()

    root = Path(args.root)
    bundle_path = (
        root
        / "models"
        / "accounting_ml_v2"
        / "accounting_model_bundle_v2.joblib"
    )
    test_path = root / "training" / "supervised_v1" / "test.jsonl"
    report_path = (
        root
        / "models"
        / "accounting_ml_v2"
        / "test_evaluation.json"
    )

    if report_path.exists():
        raise RuntimeError(
            "Test evaluation already exists; refusing to read Test again: "
            f"{report_path}"
        )
    if not bundle_path.is_file():
        raise FileNotFoundError(bundle_path)
    if not test_path.is_file():
        raise FileNotFoundError(test_path)

    bundle_sha = sha256_file(bundle_path)
    bundle = joblib.load(bundle_path)
    model_version = str(bundle.get("metadata", {}).get("model_version"))
    if model_version != "accounting-ml-v2.0.0":
        raise RuntimeError(f"Unexpected bundle model version: {model_version}")

    contract = bundle.get("metadata", {}).get("training_contract", {})
    if contract.get("test_read") is not False:
        raise RuntimeError("Bundle training contract does not confirm test_read=false")
    if contract.get("label_vocabulary") != "train_only":
        raise RuntimeError("Bundle label vocabulary is not train_only")
    if contract.get("retrieval_corpus") != "train_only":
        raise RuntimeError("Bundle retrieval corpus is not train_only")

    print("FINAL_TEST_EVALUATION = START")
    print("MODEL_VERSION =", model_version)
    print("BUNDLE_SHA256 =", bundle_sha)
    print("MODEL_SELECTION = LOCKED_FROM_VALIDATION")
    print("THRESHOLDS = LOCKED_FROM_VALIDATION")
    print("RETRAINING = DISABLED")
    print("TEST_PATH =", test_path, "(FIRST FINAL READ)")

    # This is the first and only intentional Test dataset load.
    test_texts, test_y, test_ids = base.load_dataset(test_path)
    if len(test_texts) != EXPECTED_TEST_EXAMPLES:
        raise RuntimeError(
            f"Unexpected Test example count: {len(test_texts)}"
        )

    x_test = v2.transform_texts(bundle["vectorizers"], test_texts)
    print("X_TEST shape=", x_test.shape, "nnz=", x_test.nnz)

    needs_retrieval = any(
        task.get("strategy") in {"retrieval", "hybrid"}
        for task in bundle["tasks"].values()
    )
    neighbor_idx = neighbor_sim = None
    if needs_retrieval:
        retrieval_matrix = bundle.get("retrieval_matrix")
        if retrieval_matrix is None:
            raise RuntimeError("Persisted retrieval matrix is missing")
        neighbor_idx, neighbor_sim = v2.top_neighbors(
            x_test,
            retrieval_matrix,
            5,
        )

    metrics: dict[str, Any] = {}
    predictions_for_joint: dict[str, Any] = {}

    for name in ("move_type", "journal"):
        task = bundle["tasks"][name]
        pred = predict_single(
            task,
            x_test,
            neighbor_idx,
            neighbor_sim,
        )
        task_metrics = {
            "test_examples": len(test_texts),
            "strategy": task["strategy"],
            "retrieval_k_locked_from_validation": task.get("retrieval_k"),
            "test_true_classes": sorted(set(str(v) for v in test_y[name])),
            **v2.single_metrics(test_y[name], pred),
        }
        metrics[name] = task_metrics
        predictions_for_joint[name] = np.asarray(pred, dtype=object)
        print(
            "TEST_METRICS",
            name,
            json.dumps(task_metrics, ensure_ascii=False),
        )

    for name in (
        "debit_accounts",
        "credit_accounts",
        "taxes",
        "analytics",
    ):
        task = bundle["tasks"][name]
        pred_train, linear_scores = predict_multi(
            task,
            x_test,
            neighbor_idx,
            neighbor_sim,
        )
        task_metrics = multi_test_metrics(
            task,
            test_y[name],
            pred_train,
            linear_scores,
        )
        metrics[name] = task_metrics
        predictions_for_joint[name] = pred_train
        print(
            "TEST_METRICS",
            name,
            json.dumps(task_metrics, ensure_ascii=False),
        )

    # Strict joint classification exact-match across all six classification tasks.
    joint = np.ones(len(test_texts), dtype=bool)
    joint &= predictions_for_joint["move_type"] == np.asarray(
        test_y["move_type"], dtype=object
    )
    joint &= predictions_for_joint["journal"] == np.asarray(
        test_y["journal"], dtype=object
    )

    for name in (
        "debit_accounts",
        "credit_accounts",
        "taxes",
        "analytics",
    ):
        task = bundle["tasks"][name]
        classes = [str(v) for v in task["binarizer"].classes_.tolist()]
        true_known = v2.encode_known(test_y[name], classes)
        unseen_per_row = np.asarray(
            [
                any(str(label) not in set(classes) for label in labels)
                for labels in test_y[name]
            ],
            dtype=bool,
        )
        exact_known = np.all(
            predictions_for_joint[name] == true_known,
            axis=1,
        )
        joint &= exact_known & ~unseen_per_row

    joint_exact = float(joint.mean())

    generalization_gap: dict[str, Any] = {}
    for name, task_metrics in metrics.items():
        validation = validation_reference(bundle, name)
        metric_name, test_value = primary_metric(name, task_metrics)
        validation_value = float(validation.get(metric_name, 0.0))
        generalization_gap[name] = {
            "primary_metric": metric_name,
            "validation": validation_value,
            "test": test_value,
            "test_minus_validation": test_value - validation_value,
        }

    report = {
        "schema": REPORT_SCHEMA,
        "evaluated_at": utc_now(),
        "model_version": model_version,
        "bundle_path": str(bundle_path),
        "bundle_sha256": bundle_sha,
        "test_path": str(test_path),
        "test_examples": len(test_texts),
        "test_ids_sha256": hashlib.sha256(
            "\n".join(test_ids).encode("utf-8")
        ).hexdigest(),
        "evaluation_contract": {
            "retraining": False,
            "threshold_tuning": False,
            "strategy_tuning": False,
            "feature_tuning": False,
            "label_vocabulary_mutation": False,
            "retrieval_corpus_mutation": False,
            "bundle_immutable_during_test": True,
        },
        "metrics": metrics,
        "classification_bundle_joint_exact_match": joint_exact,
        "generalization_gap": generalization_gap,
    }

    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print("CLASSIFICATION_BUNDLE_JOINT_EXACT_MATCH =", joint_exact)
    print("TEST_REPORT =", report_path)
    print("MODEL_BUNDLE_SHA256 =", bundle_sha)
    print("TEST_EXAMPLES =", len(test_texts))
    print("NO_RETRAIN_ON_TEST=PASS")
    print("NO_THRESHOLD_TUNING_ON_TEST=PASS")
    print("NO_STRATEGY_TUNING_ON_TEST=PASS")
    print("TEST_EVALUATION_LOCK=PASS")
    print("FINAL_TEST_EVALUATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
