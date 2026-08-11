from app.erp.provider_catalog import public_erp_provider_catalog
from app.services.external_llm_providers import external_llm_provider_registry


def test_external_llm_registry_builds_provider_specific_requests() -> None:
    allowed = {
        "openai:gpt-5.6-sol",
        "anthropic:claude-sonnet-5",
        "google:gemini-3.6-flash",
        "xai:grok-4.5",
    }
    catalog = external_llm_provider_registry.catalog(allowed)
    assert {provider["key"] for provider in catalog} == {"openai", "anthropic", "google", "xai"}
    assert external_llm_provider_registry.get("openai").adapter.endpoint("gpt-5.6-sol") == "https://api.openai.com/v1/responses"
    assert "gemini-3.6-flash" in external_llm_provider_registry.get("google").adapter.endpoint("gemini-3.6-flash")
    assert external_llm_provider_registry.get("xai").adapter.headers("secret")["Authorization"] == "Bearer secret"


def test_provider_adapters_normalize_to_one_application_contract() -> None:
    openai = external_llm_provider_registry.get("openai").adapter
    anthropic = external_llm_provider_registry.get("anthropic").adapter
    google = external_llm_provider_registry.get("google").adapter
    xai = external_llm_provider_registry.get("xai").adapter
    expected = {"content": [{"type": "text", "text": '{"status":"ok"}'}]}
    assert openai.normalize_response({"output_text": '{"status":"ok"}'}) == expected
    assert anthropic.normalize_response({"content": [{"text": '{"status":"ok"}'}]}) == expected
    assert google.normalize_response({"candidates": [{"content": {"parts": [{"text": '{"status":"ok"}'}]}}]}) == expected
    assert xai.normalize_response({"choices": [{"message": {"content": '{"status":"ok"}'}}]}) == expected


def test_erp_catalog_distinguishes_real_connectors_from_planned_adapters() -> None:
    catalog = public_erp_provider_catalog()
    supported = [provider for provider in catalog if provider["implemented"]]
    assert [provider["key"] for provider in supported] == ["odoo"]
    assert {provider["key"] for provider in catalog} >= {
        "sap_s4hana", "oracle_fusion", "dynamics_365", "zoho_books", "qoyod", "daftra"
    }
