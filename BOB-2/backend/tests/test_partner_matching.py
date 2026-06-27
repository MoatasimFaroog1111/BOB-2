from app.api.v1.erp import _closest_partner_by_name


def test_closest_partner_matches_spelling_variation():
    partners = [
        {"id": 1, "name": "Al Rajhi Trading Company"},
        {"id": 2, "name": "National Supplies"},
    ]

    partner_id, partner_name, score = _closest_partner_by_name(partners, "Al Rajhy Tradding Co")

    assert partner_id == 1
    assert partner_name == "Al Rajhi Trading Company"
    assert score >= 0.5


def test_closest_partner_matches_arabic_variation():
    partners = [
        {"id": 11, "name": "مؤسسة الراجحي التجارية"},
        {"id": 12, "name": "شركة التوريدات الحديثة"},
    ]

    partner_id, partner_name, score = _closest_partner_by_name(partners, "الراجحى التجاريه")

    assert partner_id == 11
    assert partner_name == "مؤسسة الراجحي التجارية"
    assert score >= 0.5


def test_closest_partner_returns_none_for_distant_name():
    partners = [
        {"id": 21, "name": "Future Vision Group"},
        {"id": 22, "name": "Blue Ocean Logistics"},
    ]

    partner_id, partner_name, score = _closest_partner_by_name(partners, "Completely Different Vendor")

    assert partner_id is None
    assert partner_name == ""
    assert score == 0.0
