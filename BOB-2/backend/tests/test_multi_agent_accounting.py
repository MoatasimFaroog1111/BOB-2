from app.services.llm_accounting_reasoner import LLMAccountingReasoner
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
    assert result["llm_reasoning"]["status"] in {"disabled_no_api_key", "success", "failed"}
    assert "reasoning" in result["llm_reasoning"]


def test_multi_agent_workflow_requires_enough_text():
    try:
        AccountingMultiAgentOrchestrator().run(text="short")
    except ValueError as exc:
        assert "too short" in str(exc).lower()
    else:
        raise AssertionError("Expected ValueError for short text")


def test_agents_capabilities_endpoint(client, auth_headers):
    response = client.get("/api/v1/agents/capabilities", headers=auth_headers)

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


def test_agents_run_workflow_endpoint_handles_arabic_tax_invoice(client, auth_headers):
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
        headers=auth_headers,
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
    assert payload["llm_reasoning"]["provider"]
    assert payload["llm_reasoning"]["model"]

    tax_agent = next(item for item in payload["agent_findings"] if item["agent"] == "TaxAgent")
    assert tax_agent["details"]["vat_signals"] is True
    assert tax_agent["details"]["amount_check"]["possible_15_percent_vat"] is True


def test_llm_reasoner_is_explicitly_disabled_without_api_key():
    result = LLMAccountingReasoner(api_key="").analyze(
        text="Tax Invoice total SAR 1150 VAT SAR 150",
        source_type="invoice",
        extracted_signals={"amounts": ["1150", "150"], "dates": [], "references": [], "party_candidates": []},
        agent_findings=[],
        conflicts=[],
        final_recommendation={"approval_required": True, "auto_posted_to_erp": False},
    )

    assert result.status == "disabled_no_api_key"
    assert result.reasoning is None
    assert result.error


def test_llm_reasoner_parses_real_provider_shape_without_network():
    class FakeReasoner(LLMAccountingReasoner):
        def _post_chat_completion(self, payload):
            assert payload["messages"]
            return {
                "choices": [
                    {
                        "message": {
                            "content": """
                            {
                              "summary": "Invoice appears valid but needs approval.",
                              "document_assessment": {"document_type": "invoice"},
                              "vat_assessment": {"vat_rate": "15%", "treatment": "input VAT review"},
                              "journal_entry_recommendation": {"debit": "Expense", "credit": "Accounts payable"},
                              "risks": ["Confirm supplier VAT registration"],
                              "questions_for_accountant": ["Is the supplier approved?"],
                              "confidence_score": 0.82
                            }
                            """
                        }
                    }
                ]
            }

    result = FakeReasoner(api_key="fake-test-key").analyze(
        text="Tax Invoice total SAR 1150 VAT SAR 150",
        source_type="invoice",
        extracted_signals={"amounts": ["1150", "150"], "dates": [], "references": [], "party_candidates": []},
        agent_findings=[],
        conflicts=[],
        final_recommendation={"approval_required": True, "auto_posted_to_erp": False},
    )

    assert result.status == "success"
    assert result.reasoning is not None
    assert result.reasoning["confidence_score"] == 0.82
    assert result.reasoning["audit_safe"]["auto_posted_to_erp"] is False
    assert result.reasoning["audit_safe"]["approval_required"] is True
