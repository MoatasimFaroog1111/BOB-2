"""Regenerate the local name-matching model artifact."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.ml.name_matching.trainer import write_artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("app/ml/name_matching/model_weights.json"),
        help="JSON artifact destination.",
    )
    args = parser.parse_args()

    artifact = write_artifact(args.output)
    print(
        "trained",
        artifact["model_version"],
        "examples=",
        artifact["training_examples"],
        "output=",
        args.output,
    )


if __name__ == "__main__":
    main()
