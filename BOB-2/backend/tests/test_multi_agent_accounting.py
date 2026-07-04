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


def test_agents_capabilities_endpoint(client):
    response = client.get("/api/v1/agents/capabilities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["safety"]["auto_posting_to_erp"] is False
    assert payload["safety"]["approval_required"] is True
    assert {agent["name"] for agent in payload["agents"]} == {
        "IntakeAgent",
        "DocumentControlAgent",
        "TaxAgent",
        "JournalAgent",
        "ReviewerAgent",
    }


def test_agents_run_workflow_endpoint_handles_arabic_tax_invoice(client):
    text = """
    فاتورة ضريبية INV/2026/0002
    المورد: شركة غارديان للمقاولات الفنية
    التاريخ: 2026-07-04
    الإجمالي قبل الضريبة SAR 1,000.00
    ضريبة القيمة المضافة 15% SAR 150.00
    الإجمالي SAR 1,150.00
    """

    response = client.post(
        "/api/v1/agents/run-accounting-workflow",
        json={"text": text, "source_type": "invoice", "organization_id": 1, "language": "auto"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["source_type"] == "invoice"
    assert payload["extracted_signals"]["amounts"]
    assert payload["extracted_signals"]["dates"] == ["2026-07-04"]
    assert payload["final_recommendation"]["auto_posted_to_erp"] is False
    assert payload["final_recommendation"]["approval_required"] is True
    assert len(payload["agent_findings"]) == 5

    tax_agent = next(item for item in payload["agent_findings"] if item["agent"] == "TaxAgent")
    assert tax_agent["details"]["vat_signals"] is True
    assert tax_agent["details"]["amount_check"]["possible_15_percent_vat"] is True
