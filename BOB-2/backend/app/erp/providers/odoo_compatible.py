"""Version-aware compatibility adapter for Odoo account.account XML-RPC calls.

Odoo 18 exposes ``deprecated`` on ``account.account`` while Odoo 19 renamed the
archival flag to ``active``. Odoo 18+ also uses ``company_ids`` rather than the
older single ``company_id`` field. Upper accounting components should not need
to branch on ERP versions, so this adapter normalizes those differences at the
provider boundary.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.erp.providers.odoo import OdooProvider


class OdooAccountCompatibilityError(RuntimeError):
    pass


def _version_major(version_payload: Any) -> int:
    if isinstance(version_payload, dict):
        info = version_payload.get("server_version_info")
        if isinstance(info, (list, tuple)) and info:
            try:
                return int(info[0])
            except (TypeError, ValueError):
                pass
        raw = str(version_payload.get("server_version") or "").strip()
    else:
        raw = str(version_payload or "").strip()

    if raw:
        token = raw.split(".", 1)[0]
        try:
            return int(token)
        except ValueError:
            pass
    raise OdooAccountCompatibilityError("Unable to determine the connected Odoo major version")


def _rewrite_domain_node(node: Any, major: int) -> Any:
    if isinstance(node, tuple):
        if len(node) >= 3 and isinstance(node[0], str):
            field, operator, value, *tail = node
            if major >= 18 and field == "company_id":
                field = "company_ids"
            if major >= 19 and field == "deprecated":
                field = "active"
                if operator in {"=", "!="} and isinstance(value, bool):
                    value = not value
            return (field, operator, value, *tail)
        return tuple(_rewrite_domain_node(item, major) for item in node)

    if isinstance(node, list):
        if len(node) >= 3 and isinstance(node[0], str) and node[0] not in {"&", "|", "!"}:
            field, operator, value, *tail = node
            if major >= 18 and field == "company_id":
                field = "company_ids"
            if major >= 19 and field == "deprecated":
                field = "active"
                if operator in {"=", "!="} and isinstance(value, bool):
                    value = not value
            return [field, operator, value, *tail]
        return [_rewrite_domain_node(item, major) for item in node]

    return node


def adapt_account_search_read_request(
    major: int,
    args: list[Any],
    kwargs: dict[str, Any] | None,
) -> tuple[list[Any], dict[str, Any], dict[str, str]]:
    """Return a non-mutating Odoo-version-specific search_read request.

    The alias map records fields that must be restored to the stable shape the
    rest of the application expects.
    """

    adapted_args = deepcopy(args)
    adapted_kwargs = deepcopy(kwargs or {})
    aliases: dict[str, str] = {}

    if adapted_args:
        adapted_args[0] = _rewrite_domain_node(adapted_args[0], major)

    requested_fields = adapted_kwargs.get("fields")
    if isinstance(requested_fields, list):
        rewritten: list[str] = []
        for field in requested_fields:
            actual = field
            if major >= 18 and field == "company_id":
                actual = "company_ids"
                aliases[field] = actual
            elif major >= 19 and field == "deprecated":
                actual = "active"
                aliases[field] = actual
            if actual not in rewritten:
                rewritten.append(actual)
        adapted_kwargs["fields"] = rewritten

    return adapted_args, adapted_kwargs, aliases


def restore_account_search_read_response(
    rows: Any,
    aliases: dict[str, str],
) -> Any:
    if not isinstance(rows, list) or not aliases:
        return rows

    restored: list[Any] = []
    for row in rows:
        if not isinstance(row, dict):
            restored.append(row)
            continue

        normalized = dict(row)
        if aliases.get("deprecated") == "active":
            normalized["deprecated"] = not bool(normalized.get("active", True))
            if "active" not in aliases:
                normalized.pop("active", None)

        if aliases.get("company_id") == "company_ids":
            company_ids = normalized.get("company_ids")
            if isinstance(company_ids, (list, tuple)) and company_ids:
                normalized["company_id"] = company_ids[0]
            else:
                normalized["company_id"] = False

        restored.append(normalized)
    return restored


class CompatibleOdooProvider(OdooProvider):
    """Odoo provider that presents one stable account schema to upper layers."""

    def __init__(self, url: str, db: str, username: str, password: str):
        super().__init__(url=url, db=db, username=username, password=password)
        self._cached_major_version: int | None = None

    def _major_version(self) -> int:
        if self._cached_major_version is None:
            self._cached_major_version = _version_major(self.common.version())
        return self._cached_major_version

    def execute_kw(self, model: str, method: str, args: list, kwargs: dict | None = None):
        if model != "account.account" or method != "search_read":
            return super().execute_kw(model, method, args, kwargs)

        adapted_args, adapted_kwargs, aliases = adapt_account_search_read_request(
            self._major_version(),
            args,
            kwargs,
        )
        rows = super().execute_kw(model, method, adapted_args, adapted_kwargs)
        return restore_account_search_read_response(rows, aliases)
