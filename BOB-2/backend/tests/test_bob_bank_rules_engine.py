from __future__ import annotations

import pytest

from app.services.bank_rules_engine import (
    BankRuleDefinitionError,
    BankRulesEngine,
    validate_conditions,
)


def rule(
    *,
    rule_id: int,
    priority: int,
    conditions: list[dict],
    account_id: int = 200,
    name: str = "Fees",
):
    return {
        "rule_id": rule_id,
        "version_id": rule_id * 10,
        "version_number": 1,
        "name": name,
        "priority": priority,
        "conditions": conditions,
        "target": {
            "account_id": account_id,
            "account_name": "Other Bank Charges",
            "account_code": "400051",
        },
        "fingerprint": "a" * 64,
    }


def test_instant_payment_fees_maps_to_configured_bob_rule_account():
    engine = BankRulesEngine()
    result = engine.resolve(
        {
            "description": "OUTGOING INSTANT PAYMENT FEES REF 9988",
            "amount": -1.15,
            "row_number": 216,
        },
        [
            rule(
                rule_id=7,
                priority=10,
                conditions=[
                    {"field": "statement_text", "operator": "contains", "value": "INSTANT PAYMENT FEES"},
                    {"field": "direction", "operator": "equals", "value": "outflow"},
                ],
            )
        ],
    )

    assert result is not None
    assert result["suggested_account_id"] == 200
    assert result["bank_rule_name"] == "Fees"
    assert result["bank_rule_version_id"] == 70
    assert result["source"] == "bob_bank_rule"
    assert result["confidence"] == 1.0
    assert result["needs_review"] is False


def test_all_conditions_must_match():
    engine = BankRulesEngine()
    rules = [
        rule(
            rule_id=7,
            priority=10,
            conditions=[
                {"field": "statement_text", "operator": "contains", "value": "FEE"},
                {"field": "amount", "operator": "lte", "value": "2.00"},
            ],
        )
    ]

    assert engine.resolve({"description": "BANK FEE", "amount": -1.15}, rules) is not None
    assert engine.resolve({"description": "BANK FEE", "amount": -5.00}, rules) is None


def test_lower_priority_number_wins_when_multiple_rules_match():
    engine = BankRulesEngine()
    rules = [
        rule(
            rule_id=1,
            priority=100,
            account_id=301,
            name="General Payment",
            conditions=[{"field": "statement_text", "operator": "contains", "value": "PAYMENT"}],
        ),
        rule(
            rule_id=2,
            priority=10,
            account_id=302,
            name="Instant Payment",
            conditions=[{"field": "statement_text", "operator": "contains", "value": "INSTANT PAYMENT"}],
        ),
    ]

    result = engine.resolve({"description": "INSTANT PAYMENT REF", "amount": -10}, rules)

    assert result is not None
    assert result["bank_rule_id"] == 2
    assert result["suggested_account_id"] == 302


def test_same_priority_overlap_is_fail_closed_as_ambiguous():
    engine = BankRulesEngine()
    rules = [
        rule(
            rule_id=1,
            priority=10,
            conditions=[{"field": "statement_text", "operator": "contains", "value": "PAYMENT"}],
        ),
        rule(
            rule_id=2,
            priority=10,
            conditions=[{"field": "statement_text", "operator": "contains", "value": "INSTANT"}],
        ),
    ]

    result = engine.resolve({"description": "INSTANT PAYMENT", "amount": -10}, rules)

    assert result is not None
    assert result["ambiguous"] is True
    assert "suggested_account_id" not in result
    assert result["candidate_rule_ids"] == [1, 2]


def test_regex_is_constrained_and_dangerous_constructs_are_rejected():
    conditions = validate_conditions(
        [{"field": "statement_text", "operator": "regex", "value": r"INSTANT\s+PAYMENT\s+FEES"}]
    )
    assert conditions[0]["operator"] == "regex"

    engine = BankRulesEngine()
    result = engine.resolve(
        {"description": "INSTANT PAYMENT FEES", "amount": -1},
        [rule(rule_id=9, priority=1, conditions=conditions)],
    )
    assert result is not None

    with pytest.raises(BankRuleDefinitionError):
        engine.resolve(
            {"description": "aaaaaaaa", "amount": -1},
            [
                rule(
                    rule_id=10,
                    priority=1,
                    conditions=[{"field": "statement_text", "operator": "regex", "value": r"(a+)+$"}],
                )
            ],
        )
