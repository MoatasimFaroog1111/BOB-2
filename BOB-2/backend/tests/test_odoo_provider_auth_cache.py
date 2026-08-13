from types import SimpleNamespace

from app.erp.providers import odoo as odoo_module


class FakeCommon:
    def __init__(self):
        self.authenticate_calls = 0

    def authenticate(self, db, username, password, context):
        self.authenticate_calls += 1
        return 42


class FakeModels:
    def __init__(self):
        self.calls = []

    def execute_kw(self, db, uid, password, model, method, args, kwargs):
        self.calls.append((db, uid, model, method))
        return []


def test_execute_kw_reuses_authenticated_uid(monkeypatch):
    common = FakeCommon()
    models = FakeModels()
    monkeypatch.setattr(
        odoo_module,
        "create_odoo_server_proxies",
        lambda _url: (SimpleNamespace(normalized_url="https://odoo.example"), common, models),
    )

    provider = odoo_module.OdooProvider(
        url="https://odoo.example",
        db="tenant-db",
        username="finance@example.com",
        password="secret",
    )

    provider.execute_kw("account.journal", "search_read", [[]])
    provider.execute_kw("account.account", "search_read", [[]])
    provider.execute_kw("res.partner", "search_read", [[]])

    assert common.authenticate_calls == 1
    assert [call[1] for call in models.calls] == [42, 42, 42]
