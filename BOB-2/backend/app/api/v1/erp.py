"""Deprecated compatibility exports.

ERP HTTP operations are owned by focused component routers in this package.
"""

from app.erp.partner_matching import closest_partner as _closest_partner_by_name

__all__ = ["_closest_partner_by_name"]
