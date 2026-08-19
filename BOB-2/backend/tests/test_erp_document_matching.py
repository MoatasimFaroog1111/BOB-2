from __future__ import annotations

from app.services import erp_document_matching as matching


def test_normalize_matching_text_strips_diacritics_and_punctuation() -> None:
    assert matching.normalize_matching_text("  Invoice #123!!  ") == "invoice 123"


def test_extract_number_handles_thousands_separators() -> None:
    assert matching.extract_number("12,345.50") == 12345.50
    assert matching.extract_number(None) is None
    assert matching.extract_number("-") is None


def test_amount_score_exact_and_within_tolerance() -> None:
    assert matching.amount_score(100, 100) == 1.0
    assert matching.amount_score(100, 100.5) == 1.0
    assert matching.amount_score(100, 50) == 0.0


def test_amount_score_missing_values() -> None:
    assert matching.amount_score(None, 100) == 0.0
    assert matching.amount_score(100, None) == 0.0


def test_normalize_date_handles_multiple_formats() -> None:
    assert matching.normalize_date("2026-01-05") == "2026-01-05"
    assert matching.normalize_date("05/01/2026") == "2026-01-05"
    assert matching.normalize_date("") == ""


def test_date_score_same_and_close_dates() -> None:
    assert matching.date_score("2026-01-05", "2026-01-05") == 1.0
    assert matching.date_score("2026-01-05", "2026-01-06") == 0.85
    assert matching.date_score("", "2026-01-05") == 0.0


def test_build_confidence_label_thresholds() -> None:
    assert matching.build_confidence_label(90) == "high"
    assert matching.build_confidence_label(70) == "medium"
    assert matching.build_confidence_label(50) == "low"
    assert matching.build_confidence_label(10) == "weak"


def test_reference_score_matches_exact_reference() -> None:
    move = {"name": "INV/2026/0001", "ref": None, "payment_reference": None}
    assert matching.reference_score("Payment for INV/2026/0001 received", move) == 1.0
    assert matching.reference_score("unrelated text", move) == 0.0


def test_score_and_rank_moves_filters_and_ranks(monkeypatch) -> None:
    class FakeErp:
        def execute_kw(self, model, method, args, kwargs=None):
            return []

    class FakeConn:
        base_url = "https://erp.example"

    moves = [
        {
            "id": 1,
            "name": "INV/0001",
            "ref": "INV/0001",
            "date": "2026-01-05",
            "invoice_date": "2026-01-05",
            "amount_total": 100.0,
            "journal_id": [1, "Sales"],
            "payment_reference": None,
            "partner_id": [1, "Acme"],
            "move_type": "out_invoice",
            "attachment_ids": [],
            "line_ids": [],
        },
        {
            "id": 2,
            "name": "INV/0002",
            "ref": "INV/0002",
            "date": "2020-01-01",
            "invoice_date": "2020-01-01",
            "amount_total": 999999.0,
            "journal_id": [1, "Sales"],
            "payment_reference": None,
            "partner_id": [1, "Someone Else"],
            "move_type": "out_invoice",
            "attachment_ids": [],
            "line_ids": [],
        },
    ]

    ranked = matching.score_and_rank_moves(
        fields={},
        doc_amount=100.0,
        doc_date="2026-01-05",
        doc_desc="Invoice INV/0001 for Acme",
        moves=moves,
        vector_scores={},
        erp=FakeErp(),
        conn=FakeConn(),
    )

    assert len(ranked) == 1
    assert ranked[0]["id"] == 1
    assert ranked[0]["confidence"] in {"high", "medium", "low", "weak"}
