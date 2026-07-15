from datetime import datetime

from app.models.core import Organization, User
from app.models.external_llm import ExternalLLMPolicy
from app.security.auth import hash_password
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
    assert result["llm_reasoning"]["status"] == "disabled_no_security_context"
    assert result["llm_reasoning"]["reasoning"] is None


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
    assert payload["safety"]["external_llm_default"] == "disabled"
    assert "current DPA acknowledgement" in payload["safety"]["external_llm_requirements"]
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
    assert payload["organization_id"] == 1
    assert payload["extracted_signals"]["amounts"]
    assert payload["extracted_signals"]["dates"] == ["2026-07-04"]
    assert payload["final_recommendation"]["auto_posted_to_erp"] is False
    assert payload["final_recommendation"]["approval_required"] is True
    assert len(payload["agent_findings"]) == 5
    assert payload["llm_reasoning"]["provider"]
    assert payload["llm_reasoning"]["model"]
    assert payload["llm_reasoning"]["status"] == "blocked_by_policy"

    tax_agent = next(item for item in payload["agent_findings"] if item["agent"] == "TaxAgent")
    assert tax_agent["details"]["vat_signals"] is True
    assert tax_agent["details"]["amount_check"]["possible_15_percent_vat"] is True


def test_llm_reasoner_is_disabled_without_authenticated_security_context():
    result = LLMAccountingReasoner(api_key="configured-but-not-consent").analyze(
        text="Tax Invoice total SAR 1150 VAT SAR 150",
        source_type="invoice",
        extracted_signals={"amounts": ["1150", "150"], "dates": [], "references": [], "party_candidates": []},
        agent_findings=[],
        conflicts=[],
        final_recommendation={"approval_required": True, "auto_posted_to_erp": False},
    )

    assert result.status == "disabled_no_security_context"
    assert result.reasoning is None
    assert result.error


def test_llm_reasoner_parses_provider_shape_only_through_gateway(db, monkeypatch):
    from app.core.config import settings

    organization = Organization(id=1, name="Test Org", legal_name="Test", country="SA", is_active=True)
    user = User(
        id=1,
        organization_id=1,
        email="owner@example.test",
        full_name="Owner",
        role="owner",
        hashed_password=hash_password("Test@Pass1234!"),
        is_active=True,
    )
    db.add_all([organization, user])
    db.commit()
    db.add(
        ExternalLLMPolicy(
            organization_id=1,
            external_llm_enabled=True,
            approved_provider="deepseek",
            approved_model="deepseek-chat",
            allowed_purposes=["accounting_reasoning"],
            allow_redacted_document_text=False,
            allow_financial_values=False,
            max_redacted_text_chars=0,
            dpa_version="2026-07-v1",
            dpa_reference="DPA-TEST",
            data_residency_region="KSA",
            provider_retention_mode="contractual_zero_retention",
            accepted_by_user_id=1,
            accepted_at=datetime.utcnow(),
            policy_version=1,
        )
    )
    db.commit()
    monkeypatch.setattr(settings, "EXTERNAL_LLM_ENABLED", True)
    monkeypatch.setattr(settings, "EXTERNAL_LLM_REQUIRED_DPA_VERSION", "2026-07-v1")
    monkeypatch.setattr(settings, "EXTERNAL_LLM_ALLOWED_PROVIDERS", "deepseek")
    monkeypatch.setattr(settings, "EXTERNAL_LLM_ALLOWED_MODELS", "deepseek:deepseek-chat")

    provider_response = {
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
    call_order: list[str] = []

    class FakeGateway:
        def __init__(self, **_kwargs):
            self.api_key = ""

        def authorize(self):
            call_order.append("authorize")
            return object()

        def execute_chat_completion(self, **kwargs):
            call_order.append("execute")
            assert kwargs["structured_payload"]
            assert kwargs["raw_document_text"]
            return provider_response

    result = LLMAccountingReasoner(
        api_key="fake-test-key",
        gateway_factory=FakeGateway,
    ).analyze(
        text="Tax Invoice total SAR 1150 VAT SAR 150",
        source_type="invoice",
        extracted_signals={"amounts": ["1150", "150"], "dates": [], "references": [], "party_candidates": []},
        agent_findings=[],
        conflicts=[],
        final_recommendation={"approval_required": True, "auto_posted_to_erp": False},
        db_session=db,
        organization_id=1,
        user_id=1,
        request_id="reasoner-test-request",
    )

    assert call_order == ["authorize", "execute"]
    assert result.status == "success"
    assert result.reasoning is not None
    assert result.reasoning["confidence_score"] == 0.82
    assert result.reasoning["audit_safe"]["auto_posted_to_erp"] is False
    assert result.reasoning["audit_safe"]["approval_required"] is True
