from __future__ import annotations

from collections import Counter

from app.main import app


def test_application_has_no_duplicate_method_path_routes() -> None:
    """One public operation must have exactly one controller owner."""
    operations: list[tuple[str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if not path:
            continue
        for method in methods - {"HEAD", "OPTIONS"}:
            operations.append((method, path))

    duplicates = {
        operation: count
        for operation, count in Counter(operations).items()
        if count > 1
    }
    assert duplicates == {}, f"Duplicate API operation owners: {duplicates}"
