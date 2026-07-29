from __future__ import annotations

import inspect
from pathlib import Path


def test_active_search_modules_do_not_import_removed_legacy_modules() -> None:
    import app.api.v1.hybrid_account_partner_search as account_module
    import app.api.v1.hybrid_global_account_search_v2 as global_module

    account_source = inspect.getsource(account_module)
    global_source = inspect.getsource(global_module)

    for source in (account_source, global_source):
        assert "deterministic_account_partner_search" not in source
        assert "hybrid_global_account_search import" not in source
        assert "_read_account_lines" not in source
        assert "search_count" not in source


def test_account_search_uses_filtered_candidate_strategy() -> None:
    import app.api.v1.hybrid_account_partner_search as module

    source = inspect.getsource(module)

    assert "read_candidate_lines" in source
    assert '["account_id", "in", account_ids]' in source
    assert "discover_partner_candidates" in source


def test_shared_odoo_helpers_are_read_only() -> None:
    import app.api.v1.odoo_search_helpers as module

    source = inspect.getsource(module)

    assert '"search_read"' in source
    assert '"create"' not in source
    assert '"write"' not in source
    assert '"unlink"' not in source


def test_frontend_chat_transport_injects_selected_company() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    transport = repository_root / "frontend" / "src" / "lib" / "companyAwareFetch.ts"
    api_module = repository_root / "frontend" / "src" / "lib" / "api.ts"

    transport_source = transport.read_text(encoding="utf-8")
    api_source = api_module.read_text(encoding="utf-8")

    assert 'localStorage.getItem("selectedCompanyId")' in transport_source
    assert "body.company_id = companyId" in transport_source
    assert 'CHAT_SPREADSHEET_PATH = "/api/v1/erp/chat-spreadsheet"' in transport_source
    assert "installCompanyAwareFetch();" in api_source
