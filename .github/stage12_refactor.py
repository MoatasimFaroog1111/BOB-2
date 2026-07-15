from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "BOB-2" / "backend"
APP = BACKEND / "app"

TARGETS = [
    APP / "api" / "v1" / "erp.py",
    APP / "api" / "v1" / "journal_entry_actions.py",
    APP / "api" / "v1" / "chat_journal_lookup.py",
    APP / "api" / "v1" / "bank_posting_v2.py",
    APP / "api" / "v1" / "bank_reconciliation_entry_suggestions.py",
    APP / "api" / "v1" / "bank_reconciliation_hardening.py",
]

TENANT_IMPORT = "from app.security.tenant_scope import current_organization_id"


def run(*args: str) -> None:
    subprocess.run(args, cwd=REPO, check=True)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def is_organization_id(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute) and node.attr == "organization_id"
    ) or (
        isinstance(node, ast.Name) and node.id == "organization_id"
    )


def is_one(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value == 1


def hardcoded_lines(path: Path) -> list[int]:
    tree = ast.parse(read(path), filename=str(path))
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1:
            if isinstance(node.ops[0], (ast.Eq, ast.NotEq)) and (
                (is_organization_id(node.left) and is_one(node.comparators[0]))
                or (is_one(node.left) and is_organization_id(node.comparators[0]))
            ):
                lines.append(node.lineno)
        elif isinstance(node, ast.keyword) and node.arg == "organization_id" and is_one(node.value):
            lines.append(node.lineno)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if value is not None and is_one(value) and any(is_organization_id(target) for target in targets):
                lines.append(node.lineno)
    return sorted(set(lines))


def ensure_tenant_import(text: str) -> str:
    if TENANT_IMPORT in text:
        return text
    marker = "router = APIRouter()"
    if marker not in text:
        raise RuntimeError("Router marker not found while adding tenant import")
    return text.replace(marker, f"{TENANT_IMPORT}\n\n{marker}", 1)


def refactor_target(path: Path) -> tuple[int, list[int]]:
    text = read(path)
    original = text

    text = text.replace(
        "ERPConnection.organization_id == 1",
        "ERPConnection.organization_id == current_organization_id(required=True)",
    )
    text = re.sub(
        r"\borganization_id\s*=\s*1\b",
        "organization_id=current_organization_id(required=True)",
        text,
    )

    if text != original:
        text = ensure_tenant_import(text)
        write(path, text)

    remaining = hardcoded_lines(path)
    if remaining:
        raise RuntimeError(f"Hardcoded organization 1 remains in {path}: {remaining}")
    return original.count("organization_id"), remaining


TENANT_SCOPE = '''"""Request-bound tenant isolation for financial ORM work.

Active routes must select their authenticated organization explicitly. The
SQLAlchemy listeners below are defense in depth only: they add a current-tenant
criterion and reject cross-tenant writes. They never reinterpret a legacy
organization literal as another tenant.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

_current_organization_id: ContextVar[int | None] = ContextVar(
    "current_financial_organization_id",
    default=None,
)
_TENANT_SCOPE_EXECUTION_OPTION = "guardian_tenant_scope_applied"


class TenantScopeError(RuntimeError):
    """Raised when ORM work attempts to cross the authenticated tenant."""


def current_organization_id(*, required: bool = True) -> int | None:
    value = _current_organization_id.get()
    if value is None:
        if required:
            raise TenantScopeError("An authenticated tenant scope is required.")
        return None
    value = int(value)
    if value <= 0:
        raise TenantScopeError("The authenticated tenant identifier is invalid.")
    return value


@contextmanager
def tenant_scope(organization_id: int) -> Iterator[int]:
    organization_id = int(organization_id)
    if organization_id <= 0:
        raise TenantScopeError("The authenticated tenant identifier is invalid.")
    token: Token[int | None] = _current_organization_id.set(organization_id)
    try:
        yield organization_id
    finally:
        _current_organization_id.reset(token)


def _mapped_tenant_classes() -> tuple[type, ...]:
    from app.db.database import Base

    return tuple(
        mapper.class_
        for mapper in tuple(Base.registry.mappers)
        if hasattr(mapper.class_, "organization_id")
    )


@event.listens_for(Session, "do_orm_execute")
def _enforce_tenant_on_orm_execute(execute_state) -> None:
    organization_id = current_organization_id(required=False)
    if organization_id is None:
        return
    if execute_state.execution_options.get(_TENANT_SCOPE_EXECUTION_OPTION):
        return

    statement = execute_state.statement
    if execute_state.is_select:
        for model in _mapped_tenant_classes():
            statement = statement.options(
                with_loader_criteria(
                    model,
                    lambda cls: cls.organization_id == organization_id,
                    include_aliases=True,
                )
            )
    elif execute_state.is_update or execute_state.is_delete:
        table = getattr(statement, "table", None)
        organization_column = getattr(getattr(table, "c", None), "organization_id", None)
        if organization_column is not None:
            statement = statement.where(organization_column == organization_id)

    execute_state.statement = statement.execution_options(
        **{_TENANT_SCOPE_EXECUTION_OPTION: True}
    )


@event.listens_for(Session, "before_flush")
def _enforce_tenant_on_flush(session: Session, _flush_context, _instances) -> None:
    organization_id = current_organization_id(required=False)
    if organization_id is None:
        return

    tenant_classes = _mapped_tenant_classes()
    for obj in tuple(session.new):
        if not isinstance(obj, tenant_classes):
            continue
        existing = getattr(obj, "organization_id", None)
        if existing in {None, organization_id}:
            setattr(obj, "organization_id", organization_id)
            continue
        raise TenantScopeError("Cross-tenant object creation was denied.")

    for obj in tuple(session.dirty) + tuple(session.deleted):
        if not isinstance(obj, tenant_classes):
            continue
        if getattr(obj, "organization_id", None) != organization_id:
            raise TenantScopeError("Cross-tenant mutation was denied.")
'''


TENANT_GUARD = '''"""Static guard for explicit financial tenant selection."""

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
router = read("app/api/v1/router.py")
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

for relative in (
    "app/api/v1/erp.py",
    "app/api/v1/journal_entry_actions.py",
    "app/api/v1/chat_journal_lookup.py",
    "app/api/v1/bank_posting_v2.py",
    "app/api/v1/bank_reconciliation_entry_suggestions.py",
    "app/api/v1/bank_reconciliation_hardening.py",
):
    text = read(relative)
    require("current_organization_id" in text, f"legacy financial module must select the current tenant explicitly: {relative}")

print("Explicit financial tenant source guard passed.")
'''


DOC = '''# Explicit tenant selection for historical financial routes

Stage 12 removes the compatibility behavior that silently translated an
`organization_id == 1` predicate into the authenticated tenant.

## Runtime invariant

Every historical financial module now evaluates
`current_organization_id(required=True)` at the database selection or creation
site. Missing request tenant context fails closed. A literal for organization 1
is never reinterpreted as another organization.

SQLAlchemy tenant criteria remain as defense in depth. They can only further
restrict a query; they do not change its intended tenant. Cross-tenant creation,
mutation, and deletion continue to fail before flush.

## Covered modules

- `erp.py`
- `journal_entry_actions.py`
- `chat_journal_lookup.py`
- `bank_posting_v2.py`
- `bank_reconciliation_entry_suggestions.py`
- `bank_reconciliation_hardening.py`

The AST source gate rejects executable comparisons, assignments, or constructor
arguments that hardcode `organization_id` to 1 anywhere under `app/`.

## Scope boundary

This stage changes application source and CI only. It does not prove that the
live backend has deployed the merge commit. Telegram and external LLM execution
remain disabled in production.
'''


def update_tenant_test() -> None:
    path = BACKEND / "tests" / "test_tenant_isolation_completion.py"
    text = read(path)
    pattern = re.compile(
        r"def test_hardcoded_legacy_predicate_and_insert_are_tenant_rewritten\(db\):.*?\n\ndef test_odoo_cache_is_namespaced_by_tenant\(\):",
        re.DOTALL,
    )
    replacement = '''def test_literal_tenant_predicate_is_not_reinterpreted_and_inserts_fail_closed(db):
    _second_tenant(db)
    db.add_all(
        [
            ERPConnection(
                organization_id=1,
                provider="odoo",
                base_url="https://one.example.com",
                database_name="one",
                auth_type="password",
                encrypted_secret_ref="secretref://memory/one/1",
                is_active=True,
            ),
            ERPConnection(
                organization_id=2,
                provider="odoo",
                base_url="https://two.example.com",
                database_name="two",
                auth_type="password",
                encrypted_secret_ref="secretref://memory/two/1",
                is_active=True,
            ),
        ]
    )
    db.commit()

    with tenant_scope(2):
        # Defense-in-depth criteria must not reinterpret the literal as tenant 2.
        assert db.query(ERPConnection).filter(ERPConnection.organization_id == 1).all() == []
        selected = db.query(ERPConnection).filter(ERPConnection.organization_id == 2).all()
        assert selected
        assert {row.organization_id for row in selected} == {2}

        cross_tenant_insert = ERPConnection(
            organization_id=1,
            provider="odoo",
            base_url="https://forbidden.example.com",
            database_name="forbidden",
            auth_type="password",
            encrypted_secret_ref="secretref://memory/forbidden/1",
            is_active=True,
        )
        db.add(cross_tenant_insert)
        with pytest.raises(TenantScopeError, match="Cross-tenant object creation"):
            db.flush()
        db.rollback()

    assert current_organization_id(required=False) is None


def test_odoo_cache_is_namespaced_by_tenant():'''
    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise RuntimeError("Could not update the Stage 11 compatibility regression")
    if "import pytest" not in updated:
        updated = updated.replace("import json\n", "import json\n\nimport pytest\n", 1)
    if "TenantScopeError" not in updated.split("\n", 20)[-1]:
        updated = updated.replace(
            "from app.security.tenant_scope import current_organization_id, tenant_scope",
            "from app.security.tenant_scope import TenantScopeError, current_organization_id, tenant_scope",
        )
    write(path, updated)


def main() -> None:
    changed: list[str] = []
    for path in TARGETS:
        before = read(path)
        refactor_target(path)
        if read(path) != before:
            changed.append(path.relative_to(REPO).as_posix())

    write(APP / "security" / "tenant_scope.py", TENANT_SCOPE)
    write(BACKEND / "scripts" / "check_tenant_isolation.py", TENANT_GUARD)
    write(REPO / "BOB-2" / "LEGACY_TENANT_REWRITE_REMOVAL.md", DOC)
    update_tenant_test()

    # Remove the one-shot bootstrap from the resulting product commit.
    workflow = REPO / ".github" / "workflows" / "stage12-bootstrap.yml"
    if workflow.exists():
        workflow.unlink()
    Path(__file__).unlink()

    run("git", "config", "user.name", "guardian-stage12-bot")
    run("git", "config", "user.email", "guardian-stage12-bot@users.noreply.github.com")
    run("git", "add", "-A")
    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=REPO,
        check=False,
    )
    if diff.returncode == 0:
        print("No Stage 12 changes were required.")
        return
    run("git", "commit", "-m", "replace legacy tenant rewriting with explicit selection")
    run("git", "push", "origin", "HEAD:agent/remove-legacy-tenant-rewrite")
    print("Refactored modules:")
    for item in changed:
        print(f"- {item}")


if __name__ == "__main__":
    main()
