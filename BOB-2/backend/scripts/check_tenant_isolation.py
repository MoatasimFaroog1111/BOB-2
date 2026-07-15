"""Static guard for Stage 11 tenant-isolation invariants."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
REPO = ROOT.parent


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


dependencies = read("app/security/dependencies.py")
tenant_scope = read("app/security/tenant_scope.py")
encryption = read("app/security/encryption.py")
discovery = read("app/erp/discovery.py")
cache = read("app/erp/odoo_cache.py")
partners = read("app/api/v1/erp_partners.py")
router = read("app/api/v1/router.py")
compose = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
secret_example = (REPO / ".env.secret-store.example").read_text(encoding="utf-8")

require(
    'payload.get("organization_id") != 1' not in dependencies,
    "financial authorization must not deny every tenant except organization 1",
)
require("with tenant_scope(organization_id)" in dependencies, "financial requests must bind tenant scope")
require("yield payload" in dependencies, "tenant scope must cover endpoint execution and be released afterward")

for marker in (
    'ContextVar(',
    'replacement_traverse',
    'with_loader_criteria',
    '@event.listens_for(Session, "do_orm_execute")',
    '@event.listens_for(Session, "before_flush")',
    'Cross-tenant mutation was denied',
):
    require(marker in tenant_scope, f"tenant ORM boundary is missing: {marker}")

require("current_organization_id(required=settings.is_production)" in encryption, "ERP secrets must use request tenant")
require("settings.LEGACY_FINANCIAL_ORGANIZATION_ID" not in encryption, "legacy default tenant must not select secrets")
require("financial_kb_org_1" not in discovery, "financial discovery must not use organization 1 file")
require('f"organization_{organization_id}.json"' in discovery, "financial discovery must be tenant namespaced")
require('metadata.get("organization_id") != organization_id' in discovery, "discovery loads must verify embedded tenant identity")
require('f"org:{organization_id}|' in cache, "Odoo cache keys must include tenant identity")
require("resolve_tenant_erp" in partners, "ERP partner route must resolve the authenticated tenant explicitly")
require("ERPConnection.organization_id == 1" not in partners, "ERP partner route must not use organization 1")
require("LEGACY_FINANCIAL_ORGANIZATION_ID" not in compose, "production Compose must not define a default financial tenant")
require("LEGACY_FINANCIAL_ORGANIZATION_ID" not in secret_example, "secret-store example must not define a default tenant")

for include_line in (
    "erp_partners_router, prefix=\"/erp\"",
    "bank_reconciliation_hardening_router, prefix=\"/erp\"",
    "bank_reconciliation_entry_suggestions_router, prefix=\"/erp\"",
    "chat_journal_lookup_router, prefix=\"/erp\"",
    "erp_router, prefix=\"/erp\"",
    "journal_entry_actions_router, prefix=\"/erp\"",
    "bank_posting_v2_router, prefix=\"/erp\"",
):
    require(include_line in router, f"financial router is missing from centralized access boundary: {include_line}")

# Existing large legacy modules are quarantined behind the request tenant scope.
# New hardcoded tenant literals anywhere else fail this guard.
legacy_literal = re.compile(r"organization_id\s*(?:==|=)\s*1\b")
allowed_legacy_files = {
    "app/api/v1/erp.py",
    "app/api/v1/journal_entry_actions.py",
    "app/api/v1/chat_journal_lookup.py",
    "app/api/v1/bank_posting_v2.py",
    "app/api/v1/bank_reconciliation_entry_suggestions.py",
    "app/api/v1/bank_reconciliation_hardening.py",
}
found: set[str] = set()
for path in APP.rglob("*.py"):
    relative = path.relative_to(ROOT).as_posix()
    if legacy_literal.search(path.read_text(encoding="utf-8")):
        found.add(relative)

unexpected = found - allowed_legacy_files
require(not unexpected, f"new hardcoded organization 1 literals are forbidden: {sorted(unexpected)}")

print("Tenant isolation source guard passed.")
if found:
    print("Quarantined legacy modules protected by the ORM tenant boundary:")
    for item in sorted(found):
        print(f"- {item}")
