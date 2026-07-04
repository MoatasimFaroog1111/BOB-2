from app.services.multi_agent_accounting import AccountingMultiAgentOrchestrator


def test_multi_agent_workflow_detects_invoice_vat_and_amounts():
    text = """
    Tax Invoice INV/2026/0001
    Supplier: Guardian Technical Contracting Company
    Date: 2026-07-04
    Subtotal SAR 1,000.00
    VAT 15% SAR 150.00
    Total SAR 1,150.00
    """

    result = AccountingMultiAgentOrchestrator().run(text=text, source_type="invoice")

    assert result["status"] == "success"
    assert result["workflow"] == "gmaws_inspired_accounting_multi_agent"
    assert result["final_recommendation"]["auto_posted_to_erp"] is False
    assert result["final_recommendation"]["approval_required"] is True
    assert result["extracted_signals"]["amounts"]
    assert any(finding["agent"] == "TaxAgent" for finding in result["agent_findings"])


def test_multi_agent_workflow_requires_enough_text():
    try:
        AccountingMultiAgentOrchestrator().run(text="short")
    except ValueError as exc:
        assert "too short" in str(exc).lower()
    else:
        raise AssertionError("Expected ValueError for short text")
