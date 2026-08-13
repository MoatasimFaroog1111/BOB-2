"""Read-only Odoo adapter for accounting learning data.

No create/write/unlink/post methods are exposed. Field discovery keeps the
adapter tolerant of supported Odoo schema differences without weakening the
provider boundary. Reference catalogs can be company-scoped so multi-company
connections never enrich one company's recommendations with another company's
accounting configuration.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.ml.accounting_intelligence.contracts import (
    AccountingReferenceCatalog,
    HistoricalAccountingExample,
)
from app.ml.accounting_intelligence.feature_engineering import build_historical_feature_text


class OdooAccountingLearningSource:
    def __init__(self, erp: Any):
        self.erp = erp

    def _available_fields(self, model: str, wanted: list[str]) -> list[str]:
        try:
            metadata = self.erp.execute_kw(
                model,
                "fields_get",
                [],
                {"attributes": ["type", "string"]},
            )
            return [field for field in wanted if field in metadata]
        except Exception:
            return wanted

    def _search_read(
        self,
        model: str,
        domain: list,
        fields: list[str],
        *,
        limit: int,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "fields": self._available_fields(model, fields),
            "limit": max(1, int(limit)),
        }
        if order:
            kwargs["order"] = order
        return list(self.erp.execute_kw(model, "search_read", [domain], kwargs) or [])

    @staticmethod
    def _many2one_id(value: Any) -> int | None:
        if isinstance(value, (list, tuple)) and value:
            try:
                return int(value[0])
            except (ValueError, TypeError):
                return None
        try:
            return int(value) if value else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _many2one_name(value: Any) -> str:
        if isinstance(value, (list, tuple)) and len(value) > 1:
            return str(value[1] or "")
        return ""

    @staticmethod
    def _many2many_ids(value: Any) -> set[int]:
        result: set[int] = set()
        if isinstance(value, (list, tuple, set)):
            for item in value:
                try:
                    if isinstance(item, (list, tuple)) and item:
                        result.add(int(item[0]))
                    else:
                        result.add(int(item))
                except (TypeError, ValueError):
                    continue
        return result

    @classmethod
    def _company_scoped_rows(
        cls,
        rows: list[dict[str, Any]],
        company_id: int | None,
    ) -> list[dict[str, Any]]:
        """Keep shared records and records belonging to the selected company only."""
        if not company_id:
            return rows
        target = int(company_id)
        scoped: list[dict[str, Any]] = []
        for row in rows:
            if "company_ids" in row:
                raw_company_ids = row.get("company_ids")
                company_ids = cls._many2many_ids(raw_company_ids)
                if raw_company_ids and company_ids and target not in company_ids:
                    continue
            elif "company_id" in row:
                row_company_id = cls._many2one_id(row.get("company_id"))
                if row_company_id is not None and row_company_id != target:
                    continue
            scoped.append(row)
        return scoped

    def reference_catalog(self, *, company_id: int | None = None) -> AccountingReferenceCatalog:
        accounts = self._search_read(
            "account.account",
            [],
            ["id", "code", "name", "account_type", "reconcile", "deprecated", "company_ids"],
            limit=5000,
            order="code asc, id asc",
        )
        journals = self._search_read(
            "account.journal",
            [["active", "=", True]],
            ["id", "code", "name", "type", "active", "company_id", "default_account_id"],
            limit=500,
            order="code asc, id asc",
        )
        taxes = self._search_read(
            "account.tax",
            [["active", "=", True]],
            ["id", "name", "amount", "amount_type", "type_tax_use", "price_include", "company_id"],
            limit=1000,
            order="id asc",
        )
        partners = self._search_read(
            "res.partner",
            [["active", "=", True]],
            [
                "id", "name", "vat", "email", "phone", "is_company", "customer_rank",
                "supplier_rank", "company_id",
            ],
            limit=10000,
            order="id asc",
        )
        try:
            analytics = self._search_read(
                "account.analytic.account",
                [["active", "=", True]],
                ["id", "name", "code", "active", "company_id", "plan_id"],
                limit=5000,
                order="id asc",
            )
        except Exception:
            analytics = []
        try:
            products = self._search_read(
                "product.product",
                [["active", "=", True]],
                ["id", "name", "default_code", "categ_id", "company_id"],
                limit=10000,
                order="id asc",
            )
        except Exception:
            products = []

        return AccountingReferenceCatalog(
            accounts=tuple(self._company_scoped_rows(accounts, company_id)),
            journals=tuple(self._company_scoped_rows(journals, company_id)),
            taxes=tuple(self._company_scoped_rows(taxes, company_id)),
            partners=tuple(self._company_scoped_rows(partners, company_id)),
            analytic_accounts=tuple(self._company_scoped_rows(analytics, company_id)),
            products=tuple(self._company_scoped_rows(products, company_id)),
        )

    @staticmethod
    def _analytic_ids(value: Any) -> set[int]:
        result: set[int] = set()
        if isinstance(value, dict):
            for raw_key in value:
                for piece in str(raw_key).split(","):
                    try:
                        result.add(int(piece.strip()))
                    except (TypeError, ValueError):
                        continue
        return result

    def historical_examples(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 1000,
        company_id: int | None = None,
    ) -> list[HistoricalAccountingExample]:
        safe_limit = min(max(int(limit), 1), 5000)
        move_domain: list = [["state", "=", "posted"]]
        if date_from:
            move_domain.append(["date", ">=", date_from])
        if date_to:
            move_domain.append(["date", "<=", date_to])
        if company_id:
            move_domain.append(["company_id", "=", int(company_id)])

        moves = self._search_read(
            "account.move",
            move_domain,
            [
                "id", "name", "ref", "date", "move_type", "journal_id", "partner_id",
                "amount_total", "currency_id", "invoice_origin", "payment_reference",
                "narration", "company_id",
            ],
            limit=safe_limit,
            order="date desc, id desc",
        )
        if not moves:
            return []

        move_ids = [int(move["id"]) for move in moves]
        lines = self._search_read(
            "account.move.line",
            [["move_id", "in", move_ids]],
            [
                "id", "move_id", "name", "account_id", "partner_id", "debit", "credit",
                "balance", "tax_ids", "analytic_distribution", "product_id", "date",
            ],
            limit=min(max(safe_limit * 30, 1000), 100000),
            order="move_id asc, id asc",
        )

        try:
            attachments = self._search_read(
                "ir.attachment",
                [["res_model", "=", "account.move"], ["res_id", "in", move_ids]],
                ["id", "name", "res_id", "mimetype", "description"],
                limit=min(max(safe_limit * 6, 1000), 30000),
                order="res_id asc, id asc",
            )
        except Exception:
            attachments = []

        lines_by_move: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for line in lines:
            move_id = self._many2one_id(line.get("move_id"))
            if move_id:
                lines_by_move[move_id].append(line)

        attachments_by_move: dict[int, list[str]] = defaultdict(list)
        for attachment in attachments:
            try:
                move_id = int(attachment.get("res_id") or 0)
            except (TypeError, ValueError):
                continue
            if not move_id:
                continue
            feature = " ".join(
                str(attachment.get(key) or "").strip()
                for key in ("name", "mimetype", "description")
                if str(attachment.get(key) or "").strip()
            )
            if feature:
                attachments_by_move[move_id].append(feature[:500])

        product_catalog: dict[int, str] = {}
        product_ids = {
            self._many2one_id(line.get("product_id"))
            for line in lines
            if self._many2one_id(line.get("product_id"))
        }
        if product_ids:
            try:
                product_rows = self._search_read(
                    "product.product",
                    [["id", "in", sorted(product_ids)]],
                    ["id", "name", "default_code"],
                    limit=len(product_ids),
                    order="id asc",
                )
                product_catalog = {
                    int(row["id"]): " ".join(
                        str(row.get(key) or "").strip()
                        for key in ("default_code", "name")
                        if str(row.get(key) or "").strip()
                    )
                    for row in product_rows
                }
            except Exception:
                product_catalog = {}

        examples: list[HistoricalAccountingExample] = []
        for move in moves:
            move_id = int(move["id"])
            move_lines = lines_by_move.get(move_id, [])
            debit_accounts: set[int] = set()
            credit_accounts: set[int] = set()
            taxes: set[int] = set()
            analytics: set[int] = set()
            line_descriptions: list[str] = []
            product_names: list[str] = []

            for line in move_lines:
                account_id = self._many2one_id(line.get("account_id"))
                try:
                    debit = float(line.get("debit") or 0)
                    credit = float(line.get("credit") or 0)
                except (TypeError, ValueError):
                    debit = credit = 0.0
                if account_id and debit > 0:
                    debit_accounts.add(account_id)
                if account_id and credit > 0:
                    credit_accounts.add(account_id)
                for tax_id in line.get("tax_ids") or []:
                    try:
                        taxes.add(int(tax_id))
                    except (TypeError, ValueError):
                        continue
                analytics.update(self._analytic_ids(line.get("analytic_distribution")))
                if line.get("name"):
                    line_descriptions.append(str(line["name"])[:500])
                product_id = self._many2one_id(line.get("product_id"))
                if product_id and product_catalog.get(product_id):
                    product_names.append(product_catalog[product_id])

            partner_name = self._many2one_name(move.get("partner_id"))
            journal_name = self._many2one_name(move.get("journal_id"))
            currency_name = self._many2one_name(move.get("currency_id")) or None
            try:
                amount = float(move.get("amount_total")) if move.get("amount_total") is not None else None
            except (TypeError, ValueError):
                amount = None
            attachment_features = attachments_by_move.get(move_id, [])
            feature_text = build_historical_feature_text(
                move_name=str(move.get("name") or ""),
                reference=str(move.get("ref") or ""),
                narration=str(move.get("narration") or ""),
                payment_reference=str(move.get("payment_reference") or ""),
                invoice_origin=str(move.get("invoice_origin") or ""),
                partner_name=partner_name,
                journal_name=journal_name,
                line_descriptions=line_descriptions,
                product_names=product_names,
                attachment_features=attachment_features,
                amount=amount,
                move_type=str(move.get("move_type") or "") or None,
                currency=currency_name,
            )
            if not feature_text:
                continue
            examples.append(
                HistoricalAccountingExample(
                    source_id=move_id,
                    source_reference=f"account.move:{move_id}",
                    text=feature_text,
                    occurred_on=str(move.get("date") or "") or None,
                    amount=amount,
                    currency=currency_name,
                    move_type=str(move.get("move_type") or "") or None,
                    journal_id=self._many2one_id(move.get("journal_id")),
                    partner_id=self._many2one_id(move.get("partner_id")),
                    debit_account_ids=tuple(sorted(debit_accounts)),
                    credit_account_ids=tuple(sorted(credit_accounts)),
                    tax_ids=tuple(sorted(taxes)),
                    analytic_account_ids=tuple(sorted(analytics)),
                    attachment_features=tuple(attachment_features),
                    feature_metadata={
                        "company_id": self._many2one_id(move.get("company_id")),
                        "attachment_count": len(attachment_features),
                        "line_count": len(move_lines),
                    },
                )
            )
        return examples
