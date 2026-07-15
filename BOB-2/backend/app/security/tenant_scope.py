"""Request-bound tenant isolation for financial ORM work.

Active routes must select their authenticated organization explicitly. The
SQLAlchemy listeners below are defense in depth only: they add a current-tenant
criterion and reject cross-tenant writes. They never reinterpret a legacy
organization literal as another tenant.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

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
    from app.db.database import Base

    return tuple(
        mapper.class_
        for mapper in tuple(Base.registry.mappers)
        if hasattr(mapper.class_, "organization_id")
    )


@event.listens_for(Session, "do_orm_execute")
def _enforce_tenant_on_orm_execute(execute_state) -> None:
    organization_id = current_organization_id(required=False)
    if organization_id is None:
        return
    if execute_state.execution_options.get(_TENANT_SCOPE_EXECUTION_OPTION):
        return

    statement = execute_state.statement
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
        if existing in {None, organization_id}:
            setattr(obj, "organization_id", organization_id)
            continue
        raise TenantScopeError("Cross-tenant object creation was denied.")

    for obj in tuple(session.dirty) + tuple(session.deleted):
        if not isinstance(obj, tenant_classes):
            continue
        if getattr(obj, "organization_id", None) != organization_id:
            raise TenantScopeError("Cross-tenant mutation was denied.")
