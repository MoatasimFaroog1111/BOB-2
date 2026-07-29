"""Offline scikit-learn trainer for the local name matcher.

This module is not imported by the production request path. It exports audited
Logistic Regression coefficients to JSON so Railway inference stays lightweight
and dependency-free.
"""

from __future__ import annotations

import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.ml.name_matching.features import FEATURE_NAMES, extract_pair_features
from app.ml.name_matching.runtime import LocalNameMatcher
from app.ml.name_matching.seed_data import (
    build_training_examples,
    validation_examples,
)

MODEL_VERSION_PREFIX = "hybrid-name-matcher"
ACCEPT_THRESHOLD = 0.80
REVIEW_THRESHOLD = 0.65


def _training_digest(examples: list[tuple[str, str, int]]) -> str:
    serialized = "\n".join(
        f"{label}\t{query}\t{candidate}"
        for query, candidate, label in examples
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
    features = [
        extract_pair_features(query, candidate)
        for query, candidate, _ in examples
    ]
    labels = [label for _, _, label in examples]

    classifier = LogisticRegression(
        max_iter=4_000,
        class_weight="balanced",
        C=1.5,
        random_state=42,
    )
    classifier.fit(features, labels)

    digest = _training_digest(examples)
    artifact: dict[str, Any] = {
        "schema_version": 1,
        "model_version": f"{MODEL_VERSION_PREFIX}-{digest[:12]}",
        "model_type": "sklearn.linear_model.LogisticRegression",
        "trained_with": {
            "scikit_learn": sklearn.__version__,
            "python": platform.python_version(),
        },
        "training_examples": len(examples),
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
