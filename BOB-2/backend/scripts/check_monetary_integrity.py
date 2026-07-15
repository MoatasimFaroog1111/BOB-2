"""Fail CI when an authoritative accounting path regresses to float money."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def require(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(f"Monetary integrity control failed: {name}")
    print(f"OK: {name}")


def main() -> None:
    sources = {
        "money": source("app/core/money.py"),
        "core model": source("app/models/core.py"),
        "bank model": source("app/models/bank_reconciliation.py"),
        "journal": source("app/api/v1/journal.py"),
        "bank posting": source("app/api/v1/bank_posting_v2.py"),
        "journal actions": source("app/api/v1/journal_entry_actions.py"),
        "legacy replacements": source("app/api/v1/erp_monetary_legacy.py"),
        "API router": source("app/api/v1/router.py"),
        "bank reconciliation": source("app/erp/bank_reconciliation.py"),
        "Telegram accounting": source("app/services/telegram_accounting_service.py"),
    }

    money = sources["money"]
    for control in (
        'MONEY_QUANTUM = Decimal("0.01")',
        "ROUND_HALF_UP",
        "def parse_money(",
        "def money_to_str(",
        "def money_to_erp_float(",
        "def validate_balanced_lines(",
        "class FixedPointJSON",
    ):
        require(f"money primitive {control}", control in money)

    core = sources["core model"]
    bank_model = sources["bank model"]
    require("journal totals use NUMERIC(20,2)", core.count("Numeric(20, 2)") >= 2)
    require("journal database balance constraint", "ck_journal_entries_balanced_totals" in core)
    require("journal database positive-total constraint", "ck_journal_entries_positive_total" in core)
    require("reconciliation totals use NUMERIC(20,2)", bank_model.count("Numeric(20, 2)") >= 3)
    require("reconciliation JSON fixed-point adapter", "FixedPointJSON" in bank_model)
    require("no persisted Float columns in core model", "mapped_column(Float" not in core)
    require("no persisted Float columns in bank model", "mapped_column(Float" not in bank_model)

    for source_name in (
        "journal",
        "bank posting",
        "journal actions",
        "legacy replacements",
        "bank reconciliation",
        "Telegram accounting",
    ):
        text = sources[source_name]
        require(f"no float summation in {source_name}", "round(sum(float" not in text)
        require(f"no float finiteness gate in {source_name}", "math.isfinite" not in text)

    journal = sources["journal"]
    require("journal Decimal request amounts", "NonNegativeMoney" in journal)
    require("journal exact balance validation", "validate_balanced_lines" in journal)
    require("journal fixed-string line persistence", "canonical_money_lines" in journal)
    require("journal fixed-string audit totals", "money_to_str(total_debit)" in journal)

    posting = sources["bank posting"]
    require("bank posting Decimal requests", "NonNegativeMoney" in posting and "amount: Money" in posting)
    require("bank posting final ERP boundary helper", "money_to_erp_float" in posting)
    require("bank posting idempotency fixed amount", "money_to_str(payload.amount)" in posting)
    require("bank posting no direct amount float", "float(payload.amount" not in posting)
    require(
        "bank posting no direct line float",
        "float(line.debit" not in posting and "float(line.credit" not in posting,
    )

    actions = sources["journal actions"]
    require("journal actions Decimal request amounts", "NonNegativeMoney" in actions)
    require("journal actions exact balance validation", "validate_balanced_lines" in actions)
    require("journal actions final ERP boundary helper", "money_to_erp_float" in actions)
    require("journal actions no Optional float money", "Optional[float]" not in actions)
    require("journal actions no direct balance float", 'float(line.get("debit"' not in actions)

    reconciliation = sources["bank reconciliation"]
    require("reconciliation Transaction amount is Money", "amount: Money" in reconciliation)
    require(
        "reconciliation totals are Money",
        "statement_total: Money" in reconciliation and "ledger_total: Money" in reconciliation,
    )
    require(
        "reconciliation uses Decimal parser",
        "Optional[Decimal]" in reconciliation and "parse_money(" in reconciliation,
    )
    require("reconciliation uses exact money sum", "money_sum(" in reconciliation)
    require("reconciliation exact amount match", "statement_txn.amount == ledger_txn.amount" in reconciliation)
    require(
        "reconciliation removed float tolerance",
        "abs(s_txn.amount - l_txn.amount) < 0.01" not in reconciliation,
    )

    telegram = sources["Telegram accounting"]
    require("Telegram canonical monetary payload", "canonical_money_lines" in telegram)
    require("Telegram exact balance validation", "validate_balanced_lines" in telegram)
    require("Telegram final ERP boundary helper", "money_to_erp_float" in telegram)
    require(
        "Telegram amount stored as fixed string",
        'normalized["amount"] = money_to_str(amount)' in telegram,
    )
    require("Telegram payload declares scale", '"money_scale": 2' in telegram)
    require("Telegram no direct line float", 'float(line.get("debit"' not in telegram)
    require("Telegram no float balance tolerance", "abs(debit_total - credit_total)" not in telegram)

    replacements = sources["legacy replacements"]
    api_router = sources["API router"]
    require(
        "legacy float routes are removed before inclusion",
        "replace_unsafe_legacy_routes(erp_router)" in api_router,
    )
    require("Decimal-safe replacement router is included", "erp_monetary_legacy_router" in api_router)
    require(
        "replacement proposal requires current create permission",
        'require_permission("create_entries")' in replacements,
    )
    require(
        "replacement posting requires current Odoo permission",
        'require_permission("post_odoo_entries")' in replacements,
    )
    require(
        "replacement routes are tenant-scoped",
        "ERPConnection.organization_id == organization_id" in replacements,
    )
    require(
        "replacement registration validates exact balance",
        "validate_balanced_lines(raw_lines)" in replacements,
    )
    require("replacement registration uses boundary conversion", "money_to_erp_float" in replacements)
    require(
        "replacement registration rejects server paths",
        "Server-side file paths are no longer accepted" in replacements,
    )


if __name__ == "__main__":
    main()
