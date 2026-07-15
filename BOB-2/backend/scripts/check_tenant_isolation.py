"""Static guard for explicit financial tenant selection."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
REPO = ROOT.parent


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _is_organization_id(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute) and node.attr == "organization_id"
    ) or (
        isinstance(node, ast.Name) and node.id == "organization_id"
    )


def _is_one(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value == 1


def _hardcoded_lines(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1:
            if isinstance(node.ops[0], (ast.Eq, ast.NotEq)) and (
                (_is_organization_id(node.left) and _is_one(node.comparators[0]))
                or (_is_one(node.left) and _is_organization_id(node.comparators[0]))
            ):
                lines.append(node.lineno)
        elif isinstance(node, ast.keyword) and node.arg == "organization_id" and _is_one(node.value):
            lines.append(node.lineno)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if value is not None and _is_one(value) and any(_is_organization_id(target) for target in targets):
                lines.append(node.lineno)
    return sorted(set(lines))


dependencies = read("app/security/dependencies.py")
tenant_scope = read("app/security/tenant_scope.py")
encryption = read("app/security/encryption.py")
discovery = read("app/erp/discovery.py")
cache = read("app/erp/odoo_cache.py")
partners = read("app/api/v1/erp_partners.py")
compose = (REPO / "docker-compose.yml").read_text(encoding="utf-8-sig")
secret_example = (REPO / ".env.secret-store.example").read_text(encoding="utf-8-sig")

require("async def enforce_financial_route_permission" in dependencies, "financial tenant scope must remain in one async request context")
require("with tenant_scope(organization_id)" in dependencies, "financial requests must bind tenant scope")
require("yield payload" in dependencies, "tenant scope must cover endpoint execution")
require("with_loader_criteria" in tenant_scope, "defense-in-depth tenant criteria must remain")
require("before_flush" in tenant_scope, "cross-tenant write protection must remain")
for forbidden in ("replacement_traverse", "BindParameter", "_rewrite_legacy_organization_literal"):
    require(forbidden not in tenant_scope, f"legacy tenant reinterpretation must not return: {forbidden}")

require("current_organization_id(required=settings.is_production)" in encryption, "ERP secrets must use request tenant")
require('f"organization_{organization_id}.json"' in discovery, "financial discovery must be tenant namespaced")
require('f"org:{organization_id}|' in cache, "Odoo cache keys must include tenant identity")
require("resolve_tenant_erp" in partners, "ERP partner route must resolve the authenticated tenant explicitly")
require("LEGACY_FINANCIAL_ORGANIZATION_ID" not in compose, "production Compose must not define a default financial tenant")
require("LEGACY_FINANCIAL_ORGANIZATION_ID" not in secret_example, "secret-store example must not define a default tenant")

violations: dict[str, list[int]] = {}
for path in APP.rglob("*.py"):
    lines = _hardcoded_lines(path)
    if lines:
        violations[path.relative_to(ROOT).as_posix()] = lines
require(not violations, f"hardcoded organization 1 literals are forbidden: {violations}")

explicit_markers = {
    "app/api/v1/erp.py": "current_organization_id(required=True)",
    "app/api/v1/journal_entry_actions.py": "current_organization_id(required=True)",
    "app/api/v1/chat_journal_lookup.py": "current_organization_id(required=True)",
    "app/api/v1/bank_reconciliation_entry_suggestions.py": "current_organization_id(required=True)",
    "app/api/v1/bank_reconciliation_hardening.py": "current_organization_id(required=True)",
    "app/api/v1/bank_posting_v2.py": "ERPConnection.organization_id == int(user.organization_id)",
}
for relative, marker in explicit_markers.items():
    require(marker in read(relative), f"financial module must select the authenticated tenant explicitly: {relative}")

print("Explicit financial tenant source guard passed.")
