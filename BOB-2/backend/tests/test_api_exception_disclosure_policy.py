"""Static regression guards for API exception disclosure."""

from __future__ import annotations

import ast
from pathlib import Path


API_ROOT = Path(__file__).parents[1] / "app" / "api"


def _http_exception_details_reference(handler: ast.ExceptHandler, name: str) -> bool:
    for node in ast.walk(handler):
        if not isinstance(node, ast.Call):
            continue
        function_name = ""
        if isinstance(node.func, ast.Name):
            function_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            function_name = node.func.attr
        if function_name != "HTTPException":
            continue
        for keyword in node.keywords:
            if keyword.arg == "detail" and any(
                isinstance(child, ast.Name) and child.id == name
                for child in ast.walk(keyword.value)
            ):
                return True
    return False


def test_unexpected_exceptions_are_not_reflected_in_http_details():
    violations: list[str] = []
    for path in sorted(API_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler) or not node.name:
                continue
            if not isinstance(node.type, ast.Name) or node.type.id != "Exception":
                continue
            if _http_exception_details_reference(node, node.name):
                violations.append(f"{path.relative_to(API_ROOT)}:{node.lineno}")

    assert violations == [], (
        "Unexpected exception values must be logged server-side and mapped to a stable "
        f"public error contract, not returned to clients: {violations}"
    )
