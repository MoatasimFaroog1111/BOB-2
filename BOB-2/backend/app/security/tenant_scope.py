"""Request-bound tenant isolation for legacy financial routes.

The authenticated financial dependency binds the current organization to a
``ContextVar`` for the lifetime of the request. SQLAlchemy listeners then:

* rewrite the historical ``organization_id == 1`` predicate to the current
  organization before SQL compilation;
* append a tenant criterion to ORM SELECT statements for every mapped model
  that exposes an ``organization_id`` column;
* tenant-bind new ORM objects and reject cross-tenant mutation/deletion.

This is a compatibility boundary while legacy ERP modules are decomposed. It
must never create a default tenant when no authenticated scope is present.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria
from sqlalchemy.sql import operators, visitors
from sqlalchemy.sql.elements import BinaryExpression, BindParameter

_current_organization_id: ContextVar[int | None] = ContextVar(
    "current_financial_organization_id",
    default=None,
)
_TENANT_SCOPE_EXECUTION_OPTION = "guardian_tenant_scope_applied"


class TenantScopeError(RuntimeError):
    """Raised when ORM work attempts to cross the authenticated tenant."""


def current_organization_id(*, required: bool = True) -> int | None:
    value = _current_organization_id.get()
    if value is None:
        if required:
            raise TenantScopeError("An authenticated tenant scope is required.")
        return None
    value = int(value)
    if value <= 0:
        raise TenantScopeError("The authenticated tenant identifier is invalid.")
    return value


@contextmanager
def tenant_scope(organization_id: int) -> Iterator[int]:
    organization_id = int(organization_id)
    if organization_id <= 0:
        raise TenantScopeError("The authenticated tenant identifier is invalid.")
    token: Token[int | None] = _current_organization_id.set(organization_id)
    try:
        yield organization_id
    finally:
        _current_organization_id.reset(token)


def _mapped_tenant_classes() -> tuple[type, ...]:
    # Import lazily to avoid a database/model import cycle during application
    # bootstrap. The registry contains all models imported by active routers.
    from app.db.database import Base

    classes: list[type] = []
    for mapper in tuple(Base.registry.mappers):
        model = mapper.class_
        if hasattr(model, "organization_id"):
            classes.append(model)
    return tuple(classes)


def _rewrite_legacy_organization_literal(statement, organization_id: int):
    """Replace only equality predicates on an organization_id column.

    Existing ORM loader options are traversal boundaries. SQLAlchemy loader
    criteria objects are intentionally slot-based and cannot be cloned by the
    generic expression visitor; the WHERE expressions around them remain safe
    to rewrite.
    """

    def replace(element):
        if not isinstance(element, BinaryExpression) or element.operator is not operators.eq:
            return None

        left = element.left
        right = element.right
        if getattr(left, "name", None) == "organization_id":
            if isinstance(right, BindParameter) and right.value == 1:
                return left == organization_id
        if getattr(right, "name", None) == "organization_id":
            if isinstance(left, BindParameter) and left.value == 1:
                return organization_id == right
        return None

    loader_options = tuple(getattr(statement, "_with_options", ()))
    traversal_options = {"stop_on": loader_options} if loader_options else {}
    return visitors.replacement_traverse(statement, traversal_options, replace)


@event.listens_for(Session, "do_orm_execute")
def _enforce_tenant_on_orm_execute(execute_state) -> None:
    organization_id = current_organization_id(required=False)
    if organization_id is None:
        return
    if execute_state.execution_options.get(_TENANT_SCOPE_EXECUTION_OPTION):
        return

    statement = _rewrite_legacy_organization_literal(
        execute_state.statement,
        organization_id,
    )

    if execute_state.is_select:
        for model in _mapped_tenant_classes():
            statement = statement.options(
                with_loader_criteria(
                    model,
                    lambda cls: cls.organization_id == organization_id,
                    include_aliases=True,
                )
            )
    elif execute_state.is_update or execute_state.is_delete:
        table = getattr(statement, "table", None)
        organization_column = getattr(getattr(table, "c", None), "organization_id", None)
        if organization_column is not None:
            statement = statement.where(organization_column == organization_id)

    execute_state.statement = statement.execution_options(
        **{_TENANT_SCOPE_EXECUTION_OPTION: True}
    )


@event.listens_for(Session, "before_flush")
def _enforce_tenant_on_flush(session: Session, _flush_context, _instances) -> None:
    organization_id = current_organization_id(required=False)
    if organization_id is None:
        return

    tenant_classes = _mapped_tenant_classes()
    for obj in tuple(session.new):
        if not isinstance(obj, tenant_classes):
            continue
        existing = getattr(obj, "organization_id", None)
        if existing in {None, 1, organization_id}:
            setattr(obj, "organization_id", organization_id)
            continue
        raise TenantScopeError("Cross-tenant object creation was denied.")

    for obj in tuple(session.dirty) + tuple(session.deleted):
        if not isinstance(obj, tenant_classes):
            continue
        existing = getattr(obj, "organization_id", None)
        if existing != organization_id:
            raise TenantScopeError("Cross-tenant mutation was denied.")
