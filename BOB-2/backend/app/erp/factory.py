from app.erp.providers.odoo import OdooProvider


def get_erp_provider(
    provider: str,
    url: str,
    db: str,
    username: str,
    password: str,
):
    provider_key = provider.lower().strip()

    if provider_key == "odoo":
        return OdooProvider(
            url=url,
            db=db,
            username=username,
            password=password,
        )

    raise ValueError(f"Unsupported ERP provider: {provider}")
