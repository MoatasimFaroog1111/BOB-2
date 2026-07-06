import os
import tempfile

import pytest

from app.api.v1 import bank_reconciliation_hardening as hardening
from app.core.config import settings
from app.erp.bank_reconciliation_nlp import suggest_transaction_action
from app.erp.document_ai import GuardianDocumentAI
from app.erp.providers.odoo import OdooProvider
from app.models.bank_reconciliation import BankReconciliationAuditLog

CSV_BANK_ONLY = b"date,description,amount\n2026-07-01,Bank service fee,-15\n"
CSV_MATCHED = b"date,description,amount\n2026-07-01,Matched transfer,-15\n"


class FakeERP:
    def __init__(self, *, fail_fetch=False, journals=None, move_lines=None):
        self.fail_fetch = fail_fetch
        self.calls = []
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
        self.move_lines = move_lines if move_lines is not None else []

    def discover_bank_journals(self, company_id=None):
        return self.journals

    def fetch_bank_transactions(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_fetch:
            raise RuntimeError("odoo fetch failed")
        return self.move_lines


def _patch_erp(monkeypatch, fake):
    monkeypatch.setattr(hardening, "_get_active_erp_provider", lambda db: fake)
    return fake


def _post_statement(client, payload=CSV_BANK_ONLY, **data):
    return client.post(
        "/api/v1/erp/bank-reconciliation",
        data={"bank_journal_id": "7", **{k: str(v) for k, v in data.items()}},
        files={"statement": ("statement.csv", payload, "text/csv")},
    )


def test_oversized_bank_statement_upload_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
    too_large = b"x" * (1024 * 1024 + 1)
    response = client.post(
        "/api/v1/erp/bank-statement-parse",
        files={"statement": ("statement.csv", too_large, "text/csv")},
    )
    assert response.status_code == 413
    assert "maximum allowed size" in response.json()["detail"]


def test_bank_reconciliation_accepts_bank_journal_id(client, monkeypatch):
    fake = _patch_erp(monkeypatch, FakeERP())
    response = _post_statement(client, company_id=1)
    assert response.status_code == 200
    assert fake.calls[0]["bank_journal_id"] == 7
    assert fake.calls[0]["bank_account_id"] == 101
    assert response.json()["selected_bank_journal"]["journal_code"] == "BNK1"


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
    journal_call = calls[0]
    assert ["id", "=", 7] in journal_call[2][0]
    move_line_call = [c for c in calls if c[0] == "account.move.line"][0]
    assert ["journal_id", "in", [7]] in move_line_call[2][0]
    assert ["account_id", "in", [101]] in move_line_call[2][0]


def test_bank_journal_listing_endpoint_returns_shape(client, monkeypatch):
    _patch_erp(monkeypatch, FakeERP())
    response = client.get("/api/v1/erp/bank-journals?company_id=1")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert {"journal_id", "journal_name", "journal_code", "account_id", "account_name", "account_code", "company_id", "company_name"}.issubset(item.keys())


def test_successful_reconciliation_creates_audit_log(client, db, monkeypatch):
    fake = FakeERP(move_lines=[{"date": "2026-07-01", "name": "Matched transfer", "ref": "", "debit": 0, "credit": 15, "move_id": [1, "BNK"], "account_id": [101, "Bank"]}])
    _patch_erp(monkeypatch, fake)
    response = _post_statement(client, payload=CSV_MATCHED)
    assert response.status_code == 200
    body = response.json()
    assert body["audit_log_id"]
    log = db.query(BankReconciliationAuditLog).first()
    assert log is not None
    assert log.status == "generated"
    assert log.bank_journal_id == 7
    assert log.statement_file_hash


def test_failed_reconciliation_logs_failure_where_possible(client, db, monkeypatch):
    _patch_erp(monkeypatch, FakeERP(fail_fetch=True))
    response = _post_statement(client)
    assert response.status_code == 400
    log = db.query(BankReconciliationAuditLog).first()
    assert log is not None
    assert log.status == "failed"
    assert "odoo fetch failed" in log.error_message


def test_save_reconciliation_report_endpoint_saves_payload(client):
    payload = {
        "selected_bank_journal": {"journal_id": 7, "journal_name": "Riyad Bank", "company_id": 1},
        "statement_metadata": {"filename": "statement.csv", "size": 12, "sha256": "abc"},
        "date_range_used": {"from": "2026-07-01", "to": "2026-07-31"},
        "reconciliation_result": {"statement_total": 0, "ledger_total": 0, "difference": 0, "statement_count": 0, "ledger_count": 0, "matched": [], "smart_matched": [], "statement_only": [], "ledger_only": [], "odoo_raw_count": 0},
    }
    response = client.post("/api/v1/erp/bank-reconciliation/reports", json=payload)
    assert response.status_code == 200
    assert response.json()["report_id"]


def test_saved_report_can_be_retrieved(client):
    save_response = client.post("/api/v1/erp/bank-reconciliation/reports", json={"reconciliation_result": {"matched": [], "smart_matched": [], "statement_only": [], "ledger_only": []}})
    report_id = save_response.json()["report_id"]
    list_response = client.get("/api/v1/erp/bank-reconciliation/reports")
    assert any(item["id"] == report_id for item in list_response.json()["items"])
    get_response = client.get(f"/api/v1/erp/bank-reconciliation/reports/{report_id}")
    assert get_response.status_code == 200
    assert get_response.json()["item"]["id"] == report_id


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
