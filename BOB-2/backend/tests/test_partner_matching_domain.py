from app.erp.partner_matching import closest_partner, normalize_partner_name


def test_normalization_removes_legal_forms_and_arabic_variants() -> None:
    assert normalize_partner_name("شركة Acme LLC") == "acme"
    assert normalize_partner_name("Acme Company LLC") == "acme"


def test_closest_partner_supports_cross_lingual_transliteration() -> None:
    partners = [
        {"id": 1, "name": "Guardian Technical Contracting"},
        {"id": 2, "name": "غارديان للمقاولات الفنية"},
    ]

    partner_id, name, score = closest_partner(partners, "غارديان مقاولات")

    assert partner_id == 2
    assert name == "غارديان للمقاولات الفنية"
    assert score >= 0.5


def test_closest_partner_returns_empty_result_when_signal_is_missing() -> None:
    assert closest_partner([], "") == (None, "", 0.0)
