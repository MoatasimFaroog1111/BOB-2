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


def test_erp_connection_routes_have_a_dedicated_component_owner() -> None:
    legacy_controller = (BACKEND_APP / "api/v1/erp.py").read_text(encoding="utf-8")
    connection_controller = (BACKEND_APP / "api/v1/erp_connections.py").read_text(encoding="utf-8")
    connection_routes = (
        '"/test-connection"',
        '"/connection"',
        '"/test-saved"',
        '"/company-info-saved"',
        '"/companies"',
        '"/discover"',
        '"/discovery"',
    )
    assert all(route not in legacy_controller for route in connection_routes)
    assert all(route in connection_controller for route in connection_routes)


def test_documents_manual_entry_ui_has_a_dedicated_component_owner() -> None:
    page = (FRONTEND_SRC / "app/documents/page.tsx").read_text(encoding="utf-8")
    modal = (
        FRONTEND_SRC / "features/documents/components/ManualEntryModal.tsx"
    ).read_text(encoding="utf-8")
    assert "<ManualEntryModal" in page
    assert "Direct Paste or Manual Text Entry" not in page
    assert "Direct Paste or Manual Text Entry" in modal
