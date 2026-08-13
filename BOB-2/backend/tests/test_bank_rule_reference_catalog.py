from app.services.bank_rule_reference_catalog import BankRuleReferenceCatalogService


class FakeProvider:
    provider_name = "odoo"
    username = "finance@example.com"

    def __init__(self):
        self.calls = []

    def execute_kw(self, model, method, args, kwargs=None):
        self.calls.append((model, method))
        if model == "res.users":
            return [{"company_id": [7, "Guardian"]}]
        if model == "account.journal":
            return [{"id": 10, "code": "BNK1", "name": "Riyadh Bank", "type": "bank", "company_id": [7, "Guardian"]}]
        if model == "account.account":
            return [{"id": 100, "code": "101001", "name": "Riyadh Bank"}]
        if model == "res.partner":
            return [{"id": 200, "name": "STC", "customer_rank": 0, "supplier_rank": 1, "company_id": False}]
        if model == "account.analytic.account":
            return [{"id": 300, "name": "Head Office"}]
        raise AssertionError(f"Unexpected model: {model}")


class FakeResolver:
    def __init__(self, provider):
        self.provider = provider
        self.calls = 0

    def resolve(self, db, organization_id):
        self.calls += 1
        assert organization_id == 55
        return object(), self.provider


def test_catalog_resolves_one_provider_for_all_reference_sections():
    provider = FakeProvider()
    resolver = FakeResolver(provider)
    service = BankRuleReferenceCatalogService(resolver=resolver)

    result = service.load(None, organization_id=55)

    assert resolver.calls == 1
    assert result["company_id"] == 7
    assert result["journals"][0]["code"] == "BNK1"
    assert result["accounts"][0]["code"] == "101001"
    assert result["partners"][0]["name"] == "STC"
    assert result["analytic_accounts"][0]["name"] == "Head Office"
    assert provider.calls == [
        ("res.users", "search_read"),
        ("account.journal", "search_read"),
        ("account.account", "search_read"),
        ("res.partner", "search_read"),
        ("account.analytic.account", "search_read"),
    ]
