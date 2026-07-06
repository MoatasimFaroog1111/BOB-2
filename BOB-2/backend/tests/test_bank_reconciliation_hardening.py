import os
import tempfile

import pytest
from fastapi import HTTPException

from app.api.v1 import bank_reconciliation_hardening as hardening
from app.core.config import settings
from app.erp.bank_reconciliation_nlp import suggest_transaction_action
from app.erp.document_ai import GuardianDocumentAI
from app.erp.providers.odoo import OdooProvider
from app.models.bank_reconciliation import BankReconciliationAuditLog


class FakeERP:
    def __init__(self, journals=None):
        self.journals = journals or [
            {
                "journal_id": 7,
                "journal_name": "Riyad Bank",
                "journal_code": "BNK1",
                "account_id": 101,
                "account_name": "Riyad Bank Account",
                "account_code": "100001",
                "company_id": 1,
                "company_name": "Guardian Technical Contracting",
            }
        ]

    def discover_bank_journals(self, company_id=None):
        return self.journals


def test_upload_size_limit_matches_settings():
    assert hardening._max_upload_bytes() == settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024


def test_selected_bank_journal_is_required_when_multiple_exist():
    erp = FakeERP(journals=[
        {"journal_id": 7, "journal_name": "Riyad Bank"},
        {"journal_id": 8, "journal_name": "SNB Bank"},
    ])
    with pytest.raises(HTTPException) as exc:
        hardening._select_bank_journal(erp, company_id=1, bank_journal_id=None)
    assert exc.value.status_code == 400


def test_bank_reconciliation_accepts_bank_journal_id_selection():
    selected, journals, warning = hardening._select_bank_journal(FakeERP(), company_id=1, bank_journal_id=7)
    assert selected["journal_id"] == 7
    assert selected["account_id"] == 101
    assert journals[0]["journal_code"] == "BNK1"
    assert warning is None


def test_bank_journal_listing_shape_direct():
    item = FakeERP().discover_bank_journals(company_id=1)[0]
    assert {"journal_id", "journal_name", "journal_code", "account_id", "account_name", "account_code", "company_id", "company_name"}.issubset(item.keys())


def test_odoo_provider_filters_move_lines_by_selected_bank_journal():
    provider = object.__new__(OdooProvider)
    calls = []

    def fake_execute_kw(model, method, args, kwargs=None):
        calls.append((model, method, args, kwargs or {}))
        if model == "account.journal":
            return [{"id": 7, "name": "Riyad Bank", "code": "BNK1", "default_account_id": [101, "Bank"]}]
        if model == "account.move.line":
            return [{"date": "2026-07-01", "name": "Fee", "ref": "", "debit": 0, "credit": 15, "move_id": [1, "MISC"], "account_id": [101, "Bank"], "journal_id": [7, "BNK1"]}]
        return []

    provider.execute_kw = fake_execute_kw
    rows = provider.fetch_bank_transactions(date_from="2026-07-01", date_to="2026-07-31", company_id=1, bank_journal_id=7, bank_account_id=101)
    assert rows
    assert ["id", "=", 7] in calls[0][2][0]
    move_line_domain = [call for call in calls if call[0] == "account.move.line"][0][2][0]
    assert ["journal_id", "in", [7]] in move_line_domain
    assert ["account_id", "in", [101]] in move_line_domain


def test_audit_log_model_contains_required_audit_fields():
    log = BankReconciliationAuditLog(
        organization_id=1,
        company_id=1,
        bank_journal_id=7,
        bank_journal_name="Riyad Bank",
        statement_filename="statement.csv",
        statement_file_hash="abc123",
        statement_file_size=120,
        date_from="2026-07-01",
        date_to="2026-07-31",
        statement_total=100.0,
        ledger_total=95.0,
        difference=5.0,
        statement_count=2,
        ledger_count=2,
        matched_count=1,
        smart_matched_count=0,
        statement_only_count=1,
        ledger_only_count=1,
        odoo_raw_count=2,
        result_json={"safe_to_post": False},
        status="generated",
    )
    assert log.bank_journal_id == 7
    assert log.statement_file_hash == "abc123"
    assert log.result_json["safe_to_post"] is False


def test_save_reconciliation_report_marks_existing_audit_saved(db):
    log = hardening._create_audit_log(
        db,
        payload={"matched": [], "smart_matched": [], "statement_only": [], "ledger_only": []},
        status_value="generated",
        statement_metadata={"filename": "statement.csv", "size": 20, "sha256": "abc123"},
        selected_journal=FakeERP().journals[0],
        date_from="2026-07-01",
        date_to="2026-07-31",
        company_id=1,
    )
    response = hardening.save_reconciliation_report(hardening.SaveReconciliationReportRequest(audit_log_id=log.id), db)
    assert response["status"] == "success"
    assert db.query(BankReconciliationAuditLog).filter(BankReconciliationAuditLog.id == log.id).first().status == "saved"


def test_saved_report_can_be_serialized_with_result(db):
    log = hardening._create_audit_log(
        db,
        payload={"matched": [], "smart_matched": [], "statement_only": [], "ledger_only": [], "statement_total": 0, "ledger_total": 0, "difference": 0},
        status_value="saved",
        statement_metadata={"filename": "statement.csv", "size": 20, "sha256": "abc123"},
        selected_journal=FakeERP().journals[0],
        date_from="2026-07-01",
        date_to="2026-07-31",
        company_id=1,
    )
    serialized = hardening._audit_to_dict(log, include_result=True)
    assert serialized["id"] == log.id
    assert serialized["result_json"]["matched"] == []


@pytest.mark.parametrize(
    "description,amount,category",
    [
        ("رسوم مصرفية شهرية", -25, "bank_charge"),
        ("Monthly bank service fee", -10, "bank_charge"),
        ("Payroll salary transfer WPS", -4000, "payroll"),
        ("سداد وزارة العمل MOL", -250, "sadad_government_payment"),
    ],
)
def test_nlp_classifies_known_transaction_types(description, amount, category):
    suggestion = suggest_transaction_action({"description": description, "amount": amount, "row_number": 1}, side="bank_only")
    assert suggestion["detected_category"] == category
    assert suggestion["confidence"] >= 0.6
    assert suggestion["safe_to_post"] is False


def test_nlp_returns_needs_review_for_unclear_text():
    suggestion = suggest_transaction_action({"description": "miscellaneous unclear reference", "amount": 12.34, "row_number": 1}, side="bank_only")
    assert suggestion["detected_category"] == "needs_review"
    assert suggestion["safe_to_post"] is False


def test_vector_db_unavailable_does_not_break_nlp_suggestions(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "app.services.vector_db", None)
    suggestion = suggest_transaction_action({"description": "Bank charge", "amount": -5}, side="bank_only")
    assert suggestion["detected_category"] == "bank_charge"
    assert suggestion["nlp_signals"]["vector_db_required"] is False


def test_document_ai_safe_to_post_remains_false():
    fd, path = tempfile.mkstemp(suffix=".txt")
    try:
        os.write(fd, b"Tax invoice sample text")
        os.close(fd)
        result = GuardianDocumentAI().analyze_document(path)
        assert result["safe_to_post"] is False
    finally:
        if os.path.exists(path):
            os.remove(path)
