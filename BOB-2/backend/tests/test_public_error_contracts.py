"""Regression tests for public API error contracts."""


def test_ai_provider_error_is_structured_and_does_not_disclose_configuration():
    from app.api.errors import ai_provider_unavailable

    error = ai_provider_unavailable()

    assert error.status_code == 503
    assert error.detail == {
        "code": "ai_provider_unavailable",
        "message": "AI assistant is temporarily unavailable.",
    }
    rendered = str(error.detail)
    assert "ANTHROPIC" not in rendered
    assert "API_KEY" not in rendered
    assert "Ollama" not in rendered


def test_unexpected_operation_error_has_stable_public_contract():
    from app.api.errors import unexpected_operation_error

    try:
        raise RuntimeError("postgresql://secret@internal-host")
    except RuntimeError:
        err = unexpected_operation_error(
            code="erp_query_failed",
            message="Unable to complete the ERP request.",
            status_code=502,
        )

    assert err.status_code == 502
    assert err.detail == {
        "code": "erp_query_failed",
        "message": "Unable to complete the ERP request.",
    }
    assert "secret" not in str(err.detail)
