from __future__ import annotations

import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_APP = REPOSITORY_ROOT / "backend" / "app"
FRONTEND_SRC = REPOSITORY_ROOT / "frontend" / "src"


def _python_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
    return imports


def test_concrete_erp_providers_are_visible_only_to_composition_root() -> None:
    offenders: list[str] = []
    for path in BACKEND_APP.rglob("*.py"):
        relative = path.relative_to(BACKEND_APP).as_posix()
        if relative in {"erp/factory.py", "erp/providers/odoo.py"}:
            continue
        if any(name.startswith("app.erp.providers") for name in _python_imports(path)):
            offenders.append(relative)
    assert offenders == [], f"Concrete ERP provider imports outside composition root: {offenders}"


def test_document_page_has_no_transport_or_endpoint_knowledge() -> None:
    page = (FRONTEND_SRC / "app/documents/page.tsx").read_text(encoding="utf-8")
    assert "fetch(" not in page
    assert "API_BASE_URL" not in page
    assert "/api/v1/" not in page


def test_document_domain_model_is_framework_independent() -> None:
    model_dir = FRONTEND_SRC / "features/documents/model"
    offenders: list[str] = []
    for path in model_dir.glob("*.ts"):
        source = path.read_text(encoding="utf-8")
        if any(marker in source for marker in ("from \"react\"", "fetch(", "API_BASE_URL", "@/app/")):
            offenders.append(path.name)
    assert offenders == [], f"Document domain model depends on framework/transport: {offenders}"
