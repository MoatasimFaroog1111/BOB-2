"""Offline scikit-learn trainer for the local name matcher.

This module is not imported by the production request path. It exports audited
Logistic Regression coefficients to JSON so Railway inference stays lightweight
and dependency-free.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.ml.name_matching.features import FEATURE_NAMES, extract_pair_features
from app.ml.name_matching.odoo_feedback_features import load_feedback_document
from app.ml.name_matching.runtime import LocalNameMatcher
from app.ml.name_matching.seed_data import (
    build_training_examples,
    validation_examples,
)

MODEL_VERSION_PREFIX = "hybrid-name-matcher"
ACCEPT_THRESHOLD = 0.80
REVIEW_THRESHOLD = 0.65


def _load_feedback_examples() -> tuple[list[list[float]], list[int], dict[str, Any]]:
    document = load_feedback_document()

    if document.get("schema_version") != 1:
        raise ValueError("Unsupported Odoo feedback corpus schema.")

    if document.get("feature_names") != FEATURE_NAMES:
        raise ValueError("Odoo feedback feature schema does not match runtime.")

    raw_examples = document.get("examples")
    if not isinstance(raw_examples, list):
        raise ValueError("Odoo feedback corpus examples must be a list.")

    features: list[list[float]] = []
    labels: list[int] = []

    for index, example in enumerate(raw_examples):
        if not isinstance(example, dict):
            raise ValueError(f"Feedback example {index} must be an object.")

        label = example.get("label")
        vector = example.get("features")

        if label not in (0, 1):
            raise ValueError(f"Feedback example {index} has an invalid label.")

        if not isinstance(vector, list) or len(vector) != len(FEATURE_NAMES):
            raise ValueError(f"Feedback example {index} has an invalid vector.")

        numeric_vector = [float(value) for value in vector]

        if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in numeric_vector):
            raise ValueError(f"Feedback example {index} contains invalid values.")

        features.append(numeric_vector)
        labels.append(int(label))

    return features, labels, document


def _training_digest(
    text_examples: list[tuple[str, str, int]],
    feedback_document: dict[str, Any],
) -> str:
    payload = {
        "text_examples": [
            [query, candidate, label]
            for query, candidate, label in text_examples
        ],
        "feature_examples": feedback_document["examples"],
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _feedback_digest(feedback_document: dict[str, Any]) -> str:
    serialized = json.dumps(
        feedback_document["examples"],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def train_artifact() -> dict[str, Any]:
    try:
        import sklearn
        from sklearn.linear_model import LogisticRegression
    except ImportError as exc:
        raise RuntimeError(
            "Offline training requires requirements.ml-training.txt."
        ) from exc

    examples = build_training_examples()
    feedback_features, feedback_labels, feedback_document = _load_feedback_examples()

    features = [
        extract_pair_features(query, candidate)
        for query, candidate, _ in examples
    ]
    labels = [label for _, _, label in examples]

    features.extend(feedback_features)
    labels.extend(feedback_labels)

    classifier = LogisticRegression(
        max_iter=4_000,
        class_weight="balanced",
        C=1.5,
        random_state=42,
    )
    classifier.fit(features, labels)

    digest = _training_digest(examples, feedback_document)
    feedback_positive = sum(feedback_labels)
    feedback_negative = len(feedback_labels) - feedback_positive

    artifact: dict[str, Any] = {
        "schema_version": 1,
        "model_version": f"{MODEL_VERSION_PREFIX}-{digest[:12]}",
        "model_type": "sklearn.linear_model.LogisticRegression",
        "trained_with": {
            "scikit_learn": sklearn.__version__,
            "python": platform.python_version(),
        },
        "training_examples": len(labels),
        "positive_examples": sum(labels),
        "negative_examples": len(labels) - sum(labels),
        "feature_names": FEATURE_NAMES,
        "intercept": float(classifier.intercept_[0]),
        "coefficients": [
            float(coefficient)
            for coefficient in classifier.coef_[0]
        ],
        "accept_threshold": ACCEPT_THRESHOLD,
        "review_threshold": REVIEW_THRESHOLD,
        "rule_thresholds": {
            "strict_model_floor": 0.30,
            "relaxed_model_floor": 0.55,
            "strict_score": 0.96,
            "relaxed_score": 0.88,
        },
        "feedback_examples": len(feedback_labels),
        "feedback_positive_examples": feedback_positive,
        "feedback_negative_examples": feedback_negative,
        "feedback_corpus_sha256": _feedback_digest(feedback_document),
        "training_digest_sha256": digest,
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    validate_artifact(artifact)
    return artifact


def validate_artifact(artifact: dict[str, Any]) -> None:
    matcher = LocalNameMatcher(artifact)
    failures: list[str] = []

    for query, candidate, expected_label in validation_examples():
        result = matcher.evaluate(query, candidate)
        predicted_label = int(result.score >= matcher.accept_threshold)

        if predicted_label != expected_label:
            failures.append(
                f"{query!r} vs {candidate!r}: "
                f"expected={expected_label} score={result.score:.4f} "
                f"reason={result.reason}"
            )

    if failures:
        joined = "\n".join(failures)
        raise RuntimeError(f"Name matcher validation failed:\n{joined}")


def write_artifact(output_path: Path) -> dict[str, Any]:
    artifact = train_artifact()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(output_path)
    return artifact
