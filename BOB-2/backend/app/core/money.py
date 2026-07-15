"""Canonical fixed-point monetary primitives.

All accounting arithmetic is performed with :class:`decimal.Decimal`.  Binary
floating point is allowed only at a documented external-system boundary after
an exact, fixed-scale value has already been validated.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Annotated, Any, Iterable, Mapping

from pydantic import Field

MONEY_PRECISION = 20
MONEY_SCALE = 2
MONEY_QUANTUM = Decimal("0.01")
MONEY_ZERO = Decimal("0.00")
MONEY_MAX_ABS = Decimal("999999999999999999.99")

Money = Annotated[Decimal, Field(max_digits=MONEY_PRECISION, decimal_places=MONEY_SCALE)]
NonNegativeMoney = Annotated[
    Decimal,
    Field(ge=MONEY_ZERO, max_digits=MONEY_PRECISION, decimal_places=MONEY_SCALE),
]
PositiveMoney = Annotated[
    Decimal,
    Field(gt=MONEY_ZERO, max_digits=MONEY_PRECISION, decimal_places=MONEY_SCALE),
]


class MoneyValidationError(ValueError):
    """Raised when a value cannot be represented safely as application money."""


def parse_money(
    value: Any,
    *,
    field_name: str = "amount",
    allow_negative: bool = True,
    allow_zero: bool = True,
    reject_excess_scale: bool = False,
) -> Decimal:
    """Parse and quantize a monetary value without binary-float arithmetic.

    Incoming JSON numbers may already have been decoded as ``float`` by a
    framework.  Converting through ``str`` avoids importing the float's binary
    expansion into Decimal.  When ``reject_excess_scale`` is true, callers must
    provide no more than two fractional digits instead of relying on rounding.
    """

    if isinstance(value, bool) or value is None:
        raise MoneyValidationError(f"{field_name} is not a valid monetary value")

    if isinstance(value, str):
        normalized = value.strip().replace(",", "")
    else:
        normalized = str(value)

    if not normalized:
        raise MoneyValidationError(f"{field_name} is not a valid monetary value")

    try:
        amount = Decimal(normalized)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise MoneyValidationError(f"{field_name} is not a valid monetary value") from exc

    if not amount.is_finite():
        raise MoneyValidationError(f"{field_name} must be finite")
    if abs(amount) > MONEY_MAX_ABS:
        raise MoneyValidationError(f"{field_name} exceeds the supported monetary range")
    if not allow_negative and amount < MONEY_ZERO:
        raise MoneyValidationError(f"{field_name} cannot be negative")
    if not allow_zero and amount == MONEY_ZERO:
        raise MoneyValidationError(f"{field_name} must be greater than zero")

    quantized = amount.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    if reject_excess_scale and quantized != amount:
        raise MoneyValidationError(f"{field_name} supports at most {MONEY_SCALE} decimal places")
    return quantized


def money_sum(values: Iterable[Any], *, field_name: str = "amount") -> Decimal:
    total = MONEY_ZERO
    for value in values:
        total += parse_money(value, field_name=field_name)
    return total.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def money_to_str(value: Any) -> str:
    """Return a canonical JSON/audit/idempotency representation."""

    return format(parse_money(value), f".{MONEY_SCALE}f")


def money_to_erp_float(value: Any) -> float:
    """Convert validated money at the final XML-RPC boundary only.

    Odoo's XML-RPC API expects a numeric value and does not support Decimal.
    The round-trip assertion guarantees the boundary conversion still denotes
    the exact application-scale amount.
    """

    amount = parse_money(value)
    external_value = float(money_to_str(amount))
    if parse_money(str(external_value)) != amount:
        raise MoneyValidationError("external ERP conversion changed the monetary value")
    return external_value


def validate_balanced_lines(
    lines: Iterable[Mapping[str, Any]],
    *,
    require_positive_total: bool = True,
) -> tuple[Decimal, Decimal]:
    """Validate debit/credit line semantics and exact fixed-point balance."""

    debit_total = MONEY_ZERO
    credit_total = MONEY_ZERO
    count = 0
    for index, line in enumerate(lines, start=1):
        count += 1
        debit = parse_money(
            line.get("debit", MONEY_ZERO),
            field_name=f"lines[{index}].debit",
            allow_negative=False,
            reject_excess_scale=True,
        )
        credit = parse_money(
            line.get("credit", MONEY_ZERO),
            field_name=f"lines[{index}].credit",
            allow_negative=False,
            reject_excess_scale=True,
        )
        if (debit > MONEY_ZERO) == (credit > MONEY_ZERO):
            raise MoneyValidationError(
                f"line {index} must contain exactly one positive debit or credit amount"
            )
        debit_total += debit
        credit_total += credit

    if count < 2:
        raise MoneyValidationError("at least two journal lines are required")

    debit_total = debit_total.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    credit_total = credit_total.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    if debit_total != credit_total:
        raise MoneyValidationError(
            f"journal is not balanced: debit={money_to_str(debit_total)}, "
            f"credit={money_to_str(credit_total)}"
        )
    if require_positive_total and debit_total <= MONEY_ZERO:
        raise MoneyValidationError("journal total must be greater than zero")
    return debit_total, credit_total


def canonical_money_lines(lines: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return JSON-safe lines with monetary values stored as fixed-scale strings."""

    result: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        normalized = dict(line)
        normalized["debit"] = money_to_str(
            parse_money(
                line.get("debit", MONEY_ZERO),
                field_name=f"lines[{index}].debit",
                allow_negative=False,
                reject_excess_scale=True,
            )
        )
        normalized["credit"] = money_to_str(
            parse_money(
                line.get("credit", MONEY_ZERO),
                field_name=f"lines[{index}].credit",
                allow_negative=False,
                reject_excess_scale=True,
            )
        )
        result.append(normalized)
    return result
