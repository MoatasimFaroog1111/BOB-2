from typing import Any

from app.erp.odoo_transport import create_odoo_server_proxies


class OdooProvider:
    def __init__(self, url: str, db: str, username: str, password: str):
        target, common, models = create_odoo_server_proxies(url)
        self.url = target.normalized_url
        self.db = db
        self.username = username
        self.password = password
        self.common = common
        self.models = models

    def authenticate(self) -> int:
        uid = self.common.authenticate(
            self.db,
            self.username,
            self.password,
            {},
        )

        if not uid:
            raise ValueError("Odoo authentication failed. Check database, username, or password.")

        return uid

    def execute_kw(self, model: str, method: str, args: list, kwargs: dict | None = None):
        uid = self.authenticate()
        return self.models.execute_kw(
            self.db,
            uid,
            self.password,
            model,
            method,
            args,
            kwargs or {},
        )

    def test_connection(self) -> dict[str, Any]:
        version = self.common.version()
        uid = self.authenticate()

        user_data = self.execute_kw(
            "res.users",
            "read",
            [[uid]],
            {"fields": ["name", "login", "company_id"]},
        )

        return {
            "provider": "odoo",
            "connected": True,
            "uid": uid,
            "odoo_version": version,
            "user": user_data[0] if user_data else None,
        }

    def get_company_info(self) -> dict[str, Any]:
        companies = self.execute_kw(
            "res.company",
            "search_read",
            [[]],
            {
                "fields": ["name", "email", "phone", "currency_id", "country_id"],
                "limit": 10,
            },
        )

        accounts_count = self.execute_kw(
            "account.account",
            "search_count",
            [[]],
        )

        return {
            "provider": "odoo",
            "companies": companies,
            "accounts_count": accounts_count,
        }

    def discover_accounts(self) -> list[dict[str, Any]]:
        return self.execute_kw(
            "account.account",
            "search_read",
            [[]],
            {
                "fields": ["code", "name", "account_type", "reconcile"],
                "limit": 1000,
            },
        )

    def discover_journals(self) -> list[dict[str, Any]]:
        return self.execute_kw(
            "account.journal",
            "search_read",
            [[]],
            {
                "fields": ["code", "name", "type", "active"],
                "limit": 100,
            },
        )

    def discover_bank_journals(self, company_id: int | None = None) -> list[dict[str, Any]]:
        """Return active bank journals with their default liquidity accounts.

        Odoo remains the source of truth. This method only reads journal and
        account metadata needed by the reconciliation UI and filters.
        """
        domain: list = [["type", "=", "bank"], ["active", "=", True]]
        if company_id:
            domain.append(["company_id", "=", company_id])

        journals = self.execute_kw(
            "account.journal",
            "search_read",
            [domain],
            {
                "fields": ["id", "name", "code", "type", "active", "default_account_id", "company_id"],
                "order": "company_id asc, code asc, id asc",
                "limit": 200,
            },
        )

        account_ids: list[int] = []
        for journal in journals:
            account = journal.get("default_account_id")
            if isinstance(account, list) and account:
                account_ids.append(int(account[0]))
            elif account:
                account_ids.append(int(account))

        account_map: dict[int, dict[str, Any]] = {}
        if account_ids:
            accounts = self.execute_kw(
                "account.account",
                "search_read",
                [[['id', 'in', sorted(set(account_ids))]]],
                {"fields": ["id", "code", "name"], "limit": len(set(account_ids))},
            )
            account_map = {int(acc["id"]): acc for acc in accounts}

        items: list[dict[str, Any]] = []
        for journal in journals:
            account = journal.get("default_account_id")
            account_id = account[0] if isinstance(account, list) and account else account
            account_row = account_map.get(int(account_id)) if account_id else {}
            company = journal.get("company_id")
            items.append({
                "journal_id": journal.get("id"),
                "journal_name": journal.get("name") or "",
                "journal_code": journal.get("code") or "",
                "account_id": account_id,
                "account_name": account_row.get("name") or (account[1] if isinstance(account, list) and len(account) > 1 else ""),
                "account_code": account_row.get("code") or "",
                "company_id": company[0] if isinstance(company, list) and company else company,
                "company_name": company[1] if isinstance(company, list) and len(company) > 1 else "",
            })
        return items

    def discover_taxes(self) -> list[dict[str, Any]]:
        return self.execute_kw(
            "account.tax",
            "search_read",
            [[]],
            {
                "fields": ["name", "amount", "amount_type", "type_tax_use", "price_include"],
                "limit": 100,
            },
        )

    def discover_partners(self) -> list[dict[str, Any]]:
        return self.execute_kw(
            "res.partner",
            "search_read",
            [[]],
            {
                "fields": ["name", "email", "phone", "vat", "is_company"],
                "limit": 1000,
            },
        )

    def discover_analytic_accounts(self) -> list[dict[str, Any]]:
        try:
            return self.execute_kw(
                "account.analytic.account",
                "search_read",
                [[]],
                {
                    "fields": ["name", "code", "active"],
                    "limit": 200,
                },
            )
        except Exception:
            return []

    def discover_products(self) -> list[dict[str, Any]]:
        try:
            return self.execute_kw(
                "product.product",
                "search_read",
                [[]],
                {
                    "fields": ["name", "default_code", "lst_price", "standard_price"],
                    "limit": 1000,
                },
            )
        except Exception:
            return []

    def fetch_bank_transactions(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        company_id: int | None = None,
        bank_journal_id: int | None = None,
        bank_account_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch posted Odoo bank move lines for the selected bank journal/account."""
        journal_domain: list = [["type", "=", "bank"], ["active", "=", True]]
        if company_id:
            journal_domain.append(["company_id", "=", company_id])
        if bank_journal_id:
            journal_domain.append(["id", "=", int(bank_journal_id)])

        bank_journals = self.execute_kw(
            "account.journal",
            "search_read",
            [journal_domain],
            {"fields": ["id", "name", "code", "default_account_id"], "limit": 200},
        )

        if not bank_journals:
            raise ValueError("No matching active bank journals found in Odoo.")

        journal_ids = [int(j["id"]) for j in bank_journals]
        account_ids: list[int] = []
        if bank_account_id:
            account_ids.append(int(bank_account_id))
        else:
            for journal in bank_journals:
                default_account = journal.get("default_account_id")
                if isinstance(default_account, list) and default_account:
                    account_ids.append(int(default_account[0]))
                elif default_account:
                    account_ids.append(int(default_account))

        fields = ["date", "name", "ref", "debit", "credit", "balance", "move_id", "account_id", "journal_id"]

        domain: list = [
            ["journal_id", "in", journal_ids],
            ["parent_state", "=", "posted"],
        ]
        if date_from:
            domain.append(["date", ">=", date_from])
        if date_to:
            domain.append(["date", "<=", date_to])

        if account_ids:
            filtered_domain = domain + [["account_id", "in", sorted(set(account_ids))]]
            move_lines = self.execute_kw(
                "account.move.line",
                "search_read",
                [filtered_domain],
                {"fields": fields, "order": "date asc, id asc", "limit": 10000},
            )
            if move_lines:
                return move_lines

        move_lines = self.execute_kw(
            "account.move.line",
            "search_read",
            [domain],
            {"fields": fields, "order": "date asc, id asc", "limit": 10000},
        )

        if not account_ids and move_lines:
            seen_moves: dict[int, dict] = {}
            for line in move_lines:
                move_id = line.get("move_id")
                if isinstance(move_id, list):
                    move_id = move_id[0]
                amount = abs(float(line.get("debit", 0) or 0) - float(line.get("credit", 0) or 0))
                previous = seen_moves.get(move_id)
                if previous is None or amount > abs(float(previous.get("debit", 0) or 0) - float(previous.get("credit", 0) or 0)):
                    seen_moves[move_id] = line
            move_lines = list(seen_moves.values())

        return move_lines

    def discover_employees(self) -> list[dict[str, Any]]:
        try:
            return self.execute_kw(
                "hr.employee",
                "search_read",
                [[]],
                {
                    "fields": ["name", "work_email", "work_phone"],
                    "limit": 500,
                },
            )
        except Exception:
            return []
