from datetime import datetime, timedelta

from app.ml.accounting_intelligence.contracts import AccountingReferenceCatalog
from app.ml.accounting_intelligence.feature_engineering import (
    amount_bucket,
    build_historical_feature_text,
)
from app.ml.accounting_intelligence.hybrid_learner import (
    HybridAccountingLearner,
    RetrievedLearningExample,
)
from app.ml.accounting_intelligence.odoo_learning_source import OdooAccountingLearningSource
from app.models.ai_accounting import AIDecisionAuditLog, AIDocumentEmbedding
from app.services.accounting_intelligence import LEARNING_SOURCE_TYPE, AccountingIntelligenceService


def test_feature_text_does_not_accept_target_account_fields():
    text = build_historical_feature_text(
        move_name="BILL/2026/001",
        reference="Office internet August",
        narration="STC monthly bill",
        payment_reference=None,
        invoice_origin=None,
        partner_name="stc السعودية",
        journal_name="Vendor Bills",
        line_descriptions=["Internet service"],
        product_names=["Internet"],
        attachment_features=["stc-august.pdf application/pdf"],
        amount=1150.0,
        move_type="in_invoice",
        currency="SAR",
    )
    assert "stc" in text
    assert "amount_bucket:1k_9k" in text
    # Post-generated move number and target journal are accepted only for backward
    # compatibility and deliberately ignored by the feature builder.
    assert "bill/2026/001" not in text
    assert "vendor bills" not in text
    # The builder has no account/tax/analytic target parameter, preventing target leakage by contract.
    assert "400020" not in text


def test_company_scoping_keeps_shared_and_selected_odoo_references_only():
    rows = [
        {"id": 1, "company_id": False},
        {"id": 2, "company_id": [7, "Company A"]},
        {"id": 3, "company_id": [8, "Company B"]},
        {"id": 4, "company_ids": [7, 8]},
        {"id": 5, "company_ids": [8]},
        {"id": 6, "company_ids": []},
    ]
    scoped = OdooAccountingLearningSource._company_scoped_rows(rows, 7)
    assert [row["id"] for row in scoped] == [1, 2, 4, 6]


def test_amount_bucket_is_stable_for_accounting_ranges():
    assert amount_bucket(0) == "zero"
    assert amount_bucket(99.99) == "lt_100"
    assert amount_bucket(100) == "100_999"
    assert amount_bucket(9999) == "1k_9k"
    assert amount_bucket(1000000) == "gte_1m"


def test_hybrid_learner_prefers_semantically_matching_historical_outcome():
    catalog = AccountingReferenceCatalog(
        accounts=(
            {"id": 10, "code": "400020", "name": "Telephone And Internet", "account_type": "expense"},
            {"id": 20, "code": "400010", "name": "Iqama Fees", "account_type": "expense"},
            {"id": 30, "code": "101001", "name": "Bank", "account_type": "asset_cash"},
        ),
        journals=({"id": 5, "code": "BILL", "name": "Vendor Bills", "type": "purchase"},),
        partners=({"id": 7, "name": "stc السعودية", "vat": "123"},),
    )
    examples = [
        RetrievedLearningExample(
            source_reference="account.move:1",
            text_preview="stc internet bill",
            vector=[1.0, 0.0],
            outputs={
                "debit_account_ids": [10],
                "credit_account_ids": [30],
                "journal_id": 5,
                "partner_id": 7,
                "tax_ids": [],
                "analytic_account_ids": [],
            },
            features={"amount_bucket": "1k_9k", "move_type": "in_invoice", "currency": "SAR", "expense_related": True},
        ),
        RetrievedLearningExample(
            source_reference="account.move:2",
            text_preview="iqama mol fee",
            vector=[0.0, 1.0],
            outputs={
                "debit_account_ids": [20],
                "credit_account_ids": [30],
                "journal_id": 5,
                "partner_id": None,
                "tax_ids": [],
                "analytic_account_ids": [],
            },
            features={"amount_bucket": "100_999", "move_type": "in_invoice", "currency": "SAR", "expense_related": True},
        ),
    ]

    result = HybridAccountingLearner().predict(
        query_text="STC internet monthly expense",
        query_vector=[0.99, 0.01],
        amount=1150,
        move_type_hint="in_invoice",
        currency_hint="SAR",
        catalog=catalog,
        examples=examples,
        top_k=2,
    )

    assert result["debit_accounts"][0]["id"] == 10
    assert result["credit_accounts"][0]["id"] == 30
    assert result["journals"][0]["id"] == 5
    assert result["partners"][0]["id"] == 7
    assert result["confidence"] > 0.60
    assert result["audit_safe"]["auto_posted_to_erp"] is False
    assert result["audit_safe"]["approval_required"] is True


def test_single_weak_example_cannot_create_false_high_confidence():
    catalog = AccountingReferenceCatalog(
        accounts=({"id": 10, "code": "400020", "name": "Telephone And Internet", "account_type": "expense"},),
    )
    examples = [
        RetrievedLearningExample(
            source_reference="account.move:weak",
            text_preview="different expense",
            vector=[0.2, 0.98],
            outputs={"debit_account_ids": [10]},
            features={"amount_bucket": "1k_9k", "move_type": "in_invoice", "currency": "SAR", "expense_related": True},
        )
    ]
    result = HybridAccountingLearner().predict(
        query_text="generic monthly expense",
        query_vector=[1.0, 0.0],
        amount=1500,
        move_type_hint="in_invoice",
        currency_hint="SAR",
        catalog=catalog,
        examples=examples,
        top_k=1,
    )
    assert result["debit_accounts"][0]["historical_consensus"] == 1.0
    assert result["evidence_strength"] < 0.60
    assert result["confidence"] < 0.60
    assert result["warnings"]


def test_low_evidence_never_enables_auto_posting():
    result = HybridAccountingLearner().predict(
        query_text="unknown transaction",
        query_vector=[1.0, 0.0],
        amount=None,
        move_type_hint=None,
        currency_hint=None,
        catalog=AccountingReferenceCatalog(),
        examples=[],
        top_k=5,
    )
    assert result["confidence"] == 0.0
    assert result["warnings"]
    assert result["audit_safe"]["auto_posted_to_erp"] is False


# ---------------------------------------------------------------------------
# Learning-memory status: company scoping, real last-update, and last-sync.
# ---------------------------------------------------------------------------


def _seed_learning_row(db, *, organization_id, company_id, source_reference, created_at, updated_at):
    row = AIDocumentEmbedding(
        organization_id=organization_id,
        source_type=LEARNING_SOURCE_TYPE,
        source_reference=source_reference,
        text_hash=f"hash:{source_reference}",
        text_preview="historical entry preview",
        embedding_model="test-local",
        embedding_dimension=2,
        embedding_vector=[0.25, 0.75],
        classification={
            "document_type": "erp_historical_entry",
            "outputs": {"debit_account_ids": [10], "credit_account_ids": [30]},
            "source": {"feature_metadata": {"company_id": company_id}},
        },
        confidence_score=1.0,
        created_at=created_at,
        updated_at=updated_at,
    )
    db.add(row)
    return row


def _seed_sync_log(db, *, organization_id, company_id, created_at, overrides=None):
    row = AIDecisionAuditLog(
        organization_id=organization_id,
        decision_type="erp_learning_sync",
        entity_type="accounting_intelligence",
        confidence_score=1.0,
        explanation="test learning sync",
        payload={
            "examples_read": 5,
            "created": 1,
            "updated": 2,
            "unchanged": 2,
            "vector_indexed": 3,
            "company_id": company_id,
            **(overrides or {}),
        },
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(row)
    return row


def test_status_scopes_learning_examples_to_selected_company(db):
    base = datetime(2026, 8, 1, 10, 0, 0)
    for company_id, ref in ((7, "account.move:7"), (8, "account.move:8"), (0, "account.move:legacy")):
        _seed_learning_row(
            db,
            organization_id=1,
            company_id=company_id,
            source_reference=ref,
            created_at=base,
            updated_at=base,
        )
    db.commit()

    service = AccountingIntelligenceService(db)
    org_wide = service.status(organization_id=1)
    assert org_wide["learning_examples"] == 3
    assert org_wide["company_scope"] == {"company_id": None, "applied": False}

    scoped = service.status(organization_id=1, company_id=7)
    assert scoped["learning_examples"] == 1
    assert scoped["company_scope"] == {"company_id": 7, "applied": True}
    assert service.status(organization_id=1, company_id=8)["learning_examples"] == 1
    # The legacy/unknown-company row (company_id=0) is excluded from every
    # scoped count, matching the prediction-time cross-company safety rule.


def test_status_latest_memory_update_uses_updated_at_not_created_at(db):
    base = datetime(2026, 8, 1, 10, 0, 0)
    _seed_learning_row(
        db,
        organization_id=1,
        company_id=7,
        source_reference="account.move:refreshed",
        created_at=base,
        updated_at=base + timedelta(hours=2),
    )
    _seed_learning_row(
        db,
        organization_id=1,
        company_id=7,
        source_reference="account.move:newer-created",
        created_at=base + timedelta(hours=1),
        updated_at=base + timedelta(hours=1),
    )
    db.commit()

    status = AccountingIntelligenceService(db).status(organization_id=1, company_id=7)
    assert status["latest_learning_example_at"] == (base + timedelta(hours=1)).isoformat()
    assert status["latest_learning_update_at"] == (base + timedelta(hours=2)).isoformat()


def test_status_reports_last_sync_scoped_to_company(db):
    base = datetime(2026, 8, 1, 10, 0, 0)
    _seed_sync_log(db, organization_id=1, company_id=7, created_at=base)
    _seed_sync_log(db, organization_id=1, company_id=8, created_at=base + timedelta(hours=1))
    _seed_sync_log(
        db,
        organization_id=1,
        company_id=7,
        created_at=base + timedelta(hours=2),
        overrides={"examples_read": 9, "created": 4, "updated": 3, "unchanged": 2},
    )
    db.commit()

    service = AccountingIntelligenceService(db)
    scoped = service.status(organization_id=1, company_id=7)
    assert scoped["last_sync"] is not None
    assert scoped["last_sync"]["at"] == (base + timedelta(hours=2)).isoformat()
    assert scoped["last_sync"]["summary"]["created"] == 4
    assert scoped["last_sync"]["summary"]["updated"] == 3
    assert scoped["last_sync"]["summary"]["unchanged"] == 2

    # The company-8 sync is newer than the first company-7 sync but must never
    # leak into the company-7 scoped view.
    assert scoped["last_sync"]["company_id"] == 7
    org_wide = service.status(organization_id=1)
    assert org_wide["last_sync"]["at"] == (base + timedelta(hours=2)).isoformat()


def test_status_endpoint_scopes_by_company_query_param(client, auth_headers, db):
    base = datetime(2026, 8, 1, 10, 0, 0)
    _seed_learning_row(
        db,
        organization_id=1,
        company_id=7,
        source_reference="account.move:7",
        created_at=base,
        updated_at=base,
    )
    _seed_learning_row(
        db,
        organization_id=1,
        company_id=8,
        source_reference="account.move:8",
        created_at=base,
        updated_at=base,
    )
    db.commit()

    scoped = client.get("/api/v1/accounting-intelligence/status?company_id=7", headers=auth_headers)
    assert scoped.status_code == 200, scoped.text
    assert scoped.json()["learning_examples"] == 1
    assert scoped.json()["company_scope"] == {"company_id": 7, "applied": True}
    assert scoped.json()["latest_learning_update_at"] == base.isoformat()

    org_wide = client.get("/api/v1/accounting-intelligence/status", headers=auth_headers)
    assert org_wide.status_code == 200, org_wide.text
    assert org_wide.json()["learning_examples"] == 2
    assert org_wide.json()["company_scope"] == {"company_id": None, "applied": False}

    invalid = client.get("/api/v1/accounting-intelligence/status?company_id=0", headers=auth_headers)
    assert invalid.status_code == 422
