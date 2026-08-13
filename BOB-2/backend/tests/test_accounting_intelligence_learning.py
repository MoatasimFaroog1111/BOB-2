from app.ml.accounting_intelligence.contracts import AccountingReferenceCatalog
from app.ml.accounting_intelligence.feature_engineering import (
    amount_bucket,
    build_historical_feature_text,
)
from app.ml.accounting_intelligence.hybrid_learner import (
    HybridAccountingLearner,
    RetrievedLearningExample,
)


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
    # The builder has no account/tax/analytic target parameter, preventing target leakage by contract.
    assert "400020" not in text


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
    assert result["audit_safe"]["auto_posted_to_erp"] is False
    assert result["audit_safe"]["approval_required"] is True


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
