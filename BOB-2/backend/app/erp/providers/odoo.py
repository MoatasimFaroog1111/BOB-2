import xmlrpc.client
from typing import Any


class OdooProvider:
    def __init__(self, url: str, db: str, username: str, password: str):
        self.url = url.rstrip("/")
        self.db = db
        self.username = username
        self.password = password
        self.common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

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
    ) -> list[dict[str, Any]]:
        """Fetch bank account transactions (account.move.line) from bank-type journals."""
        # Find bank journals
        journal_domain: list = [["type", "=", "bank"]]
        if company_id:
            journal_domain.append(["company_id", "=", company_id])
        bank_journals = self.execute_kw(
            "account.journal",
            "search_read",
            [journal_domain],
            {"fields": ["id", "name", "default_account_id"], "limit": 50},
        )

        if not bank_journals:
            raise ValueError("No bank journals found in Odoo.")

        journal_ids = [j["id"] for j in bank_journals]

        # Collect liquidity account IDs from bank journals
        account_ids = []
        for j in bank_journals:
            def_acc = j.get("default_account_id")
            if isinstance(def_acc, list) and def_acc:
                account_ids.append(def_acc[0])
            elif def_acc:
                account_ids.append(def_acc)

        fields = ["date", "name", "ref", "debit", "credit", "balance", "move_id", "account_id"]

        domain: list = [
            ["journal_id", "in", journal_ids],
            ["parent_state", "=", "posted"],
        ]
        if date_from:
            domain.append(["date", ">=", date_from])
        if date_to:
            domain.append(["date", "<=", date_to])

        # Try with account_id filter first (liquidity account lines only)
        if account_ids:
            filtered_domain = domain + [["account_id", "in", account_ids]]
            move_lines = self.execute_kw(
                "account.move.line",
                "search_read",
                [filtered_domain],
                {"fields": fields, "order": "date asc, id asc", "limit": 10000},
            )
            if move_lines:
                return move_lines

        # Fallback: query without account_id filter, then deduplicate
        # by keeping only one line per move_id (the one with the largest
        # abs(debit - credit), which is typically the bank-side line).
        move_lines = self.execute_kw(
            "account.move.line",
            "search_read",
            [domain],
            {"fields": fields, "order": "date asc, id asc", "limit": 10000},
        )

        if not account_ids and move_lines:
            # No account_id filter was possible; deduplicate by move_id
            seen_moves: dict[int, dict] = {}
            for line in move_lines:
                mid = line.get("move_id")
                if isinstance(mid, list):
                    mid = mid[0]
                amt = abs(float(line.get("debit", 0)) - float(line.get("credit", 0)))
                prev = seen_moves.get(mid)
                if prev is None or amt > abs(float(prev.get("debit", 0)) - float(prev.get("credit", 0))):
                    seen_moves[mid] = line
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

