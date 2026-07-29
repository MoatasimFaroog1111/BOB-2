from __future__ import annotations

import ast
import inspect

from app.api.v1.hybrid_global_account_search import _extract_global_request


def test_screenshot_prompt_routes_to_local_global_search() -> None:
    prompt = (
        "ابحث مباشرة في Odoo في جميع الحسابات واجلب لي جميع البيانات "
        "المرتبطة بالكلمة غلام سواء بالعربي ام بالانجليزي او أي كلمة قريبة منها"
    )

    assert _extract_global_request(prompt) == "غلام"


def test_all_accounts_english_prompt_is_supported() -> None:
    assert (
        _extract_global_request(
            "Search all accounts for the partner Ghulam and similar spellings"
        )
        == "Ghulam"
    )


def test_account_scoped_prompt_stays_with_account_route() -> None:
    prompt = "اجلب من الحساب 102014 كل العمليات المرتبطة بالكلمة غلام"

    assert _extract_global_request(prompt) is None


def test_unscoped_general_chat_does_not_trigger_global_odoo_scan() -> None:
    assert _extract_global_request("ما معنى حساب المصروفات؟") is None


def test_global_search_module_has_no_external_ai_import() -> None:
    import app.api.v1.hybrid_global_account_search as module

    tree = ast.parse(inspect.getsource(module))
    imported_modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[0])

    assert imported_modules.isdisjoint({"anthropic", "openai", "ollama"})
