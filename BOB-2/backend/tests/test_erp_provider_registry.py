from app.erp.factory import provider_registry


def test_major_accounting_systems_are_registered():
    assert set(provider_registry.supported_providers()) == {
        "odoo",
        "sap_s4hana",
        "oracle_fusion",
        "business_central",
        "quickbooks_online",
        "xero",
    }
