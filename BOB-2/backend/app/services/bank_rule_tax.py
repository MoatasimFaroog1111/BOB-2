"""Tax arithmetic for BOB Bank Rules.

Bank statement values represent the cash amount that actually moved. When a rule has
an approved percentage tax, that gross cash amount is split into base + tax for review.
The component is pure and owns no ERP or persistence capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.core.money import parse_money

_MONEY_QUANTUM = Decimal("0.01")
_HUNDRED = Decimal("100")


class BankRuleTaxError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TaxInclusiveSplit:
    gross: Decimal
    base: Decimal
    tax: Decimal


def split_tax_inclusive(gross_value: Any, rate_value: Any) -> TaxInclusiveSplit:
    """Split a tax-inclusive gross amount using a standard percentage tax."""
    gross = abs(parse_money(gross_value, field_name="bank_rule_tax.gross"))
    try:
        rate = Decimal(str(rate_value))
    except Exception as exc:
        raise BankRuleTaxError("Configured Bank Rule tax rate is invalid") from exc
    if rate <= 0 or rate >= _HUNDRED:
        raise BankRuleTaxError("Configured Bank Rule tax rate must be greater than 0 and less than 100")
    base = (gross / (Decimal("1") + rate / _HUNDRED)).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    tax = (gross - base).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    if base < 0 or tax <= 0 or base + tax != gross:
        raise BankRuleTaxError("Configured Bank Rule tax could not be split safely")
    return TaxInclusiveSplit(gross=gross, base=base, tax=tax)
