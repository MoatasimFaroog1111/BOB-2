from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db.database import Base
from app.models.mixins import TimestampMixin
from app.security.audit_chain import (
    AUDIT_EVENT_VERSION,
    GENESIS_HASH,
    AuditLogMutationError,
    advisory_lock_id,
    audit_scope_key,
    compute_audit_event_hash,
    utc_naive,
)


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country: Mapped[str] = mapped_column(String(100), default="Saudi Arabia", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="viewer")
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    security_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    security_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TelegramAuthorization(Base, TimestampMixin):
    """Explicit Telegram identity-to-tenant and identity-to-user binding.

    No role or permission is copied into this table. Authorization always reads the
    linked system user's current role from the users table so a role reduction takes
    effect on the next Telegram operation.
    """

    __tablename__ = "telegram_authorizations"
    __table_args__ = (
        UniqueConstraint(
            "telegram_user_id",
            "telegram_chat_id",
            name="uq_telegram_authorizations_actor_chat",
        ),
        CheckConstraint("telegram_user_id > 0", name="ck_telegram_authorizations_user_positive"),
        CheckConstraint("telegram_chat_id <> 0", name="ck_telegram_authorizations_chat_nonzero"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), index=True, nullable=False
    )
    system_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    allow_group_chats: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TelegramApprovalOperation(Base, TimestampMixin):
    """Durable, actor-bound, one-time approval for a Telegram accounting operation."""

    __tablename__ = "telegram_approval_operations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','processing','posted','cancelled','expired','failed','revoked')",
            name="ck_telegram_approval_operations_status",
        ),
        CheckConstraint("telegram_user_id > 0", name="ck_telegram_approval_operations_user_positive"),
        CheckConstraint("telegram_chat_id <> 0", name="ck_telegram_approval_operations_chat_nonzero"),
        UniqueConstraint(
            "approval_token_hash",
            name="uq_telegram_approval_operations_token_hash",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), index=True, nullable=False
    )
    authorization_id: Mapped[int] = mapped_column(
        ForeignKey("telegram_authorizations.id"), index=True, nullable=False
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    system_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    source: Mapped[str] = mapped_column(String(50), default="telegram", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    posted_move_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    attachment_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class AuthSession(Base, TimestampMixin):
    """Server-side session state for access/refresh token revocation and rotation."""

    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    family_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), index=True, nullable=False
    )
    user_security_version: Mapped[int] = mapped_column(Integer, nullable=False)
    access_jti: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    refresh_jti: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, index=True, nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ERPConnection(Base, TimestampMixin):
    __tablename__ = "erp_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    database_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth_type: Mapped[str] = mapped_column(String(100), nullable=False)
    encrypted_secret_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    uploaded_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(100), default="uploaded", nullable=False)
    classification: Mapped[str | None] = mapped_column(String(100), nullable=True)


class AuditLogChainHead(Base):
    __tablename__ = "audit_log_chain_heads"

    scope_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    last_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_hash: Mapped[str] = mapped_column(String(64), nullable=False, default=GENESIS_HASH)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"
    __table_args__ = (
        UniqueConstraint("scope_key", "sequence_number", name="uq_audit_logs_scope_sequence"),
        UniqueConstraint("event_hash", name="uq_audit_logs_event_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    scope_key: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    sequence_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, default=AUDIT_EVENT_VERSION)


class ApprovalRequest(Base, TimestampMixin):
    __tablename__ = "approval_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    requested_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    request_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(100), default="pending", nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ExtractedFinancialObject(Base, TimestampMixin):
    __tablename__ = "extracted_financial_objects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    object_type: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence_score: Mapped[str | None] = mapped_column(String(50), nullable=True)
    extracted_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    validation_status: Mapped[str] = mapped_column(String(100), default="pending_validation", nullable=False)


class JournalEntryRecord(Base, TimestampMixin):
    """Tenant-isolated, durable journal entry snapshot."""

    __tablename__ = "journal_entries"
    __table_args__ = (
        CheckConstraint("total_debit > 0", name="ck_journal_entries_positive_total"),
        CheckConstraint("total_debit = total_credit", name="ck_journal_entries_balanced_totals"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    reference: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    memo: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True, nullable=False)
    lines: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    total_debit: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    total_credit: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)


class VectorRecord(Base, TimestampMixin):
    """Tenant-isolated embedding storage without an exposed vector database server."""

    __tablename__ = "vector_records"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "collection_name",
            "document_key",
            name="uq_vector_records_tenant_collection_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=False)
    collection_name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    document_key: Mapped[str] = mapped_column(String(128), nullable=False)
    document: Mapped[str] = mapped_column(Text, nullable=False)
    record_metadata: Mapped[dict] = mapped_column(JSON, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(JSON, nullable=False)


def _create_audit_append_only_triggers(target, connection, **_kwargs) -> None:
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS trg_audit_logs_no_update
            BEFORE UPDATE ON audit_logs
            BEGIN
                SELECT RAISE(ABORT, 'audit_logs is append-only');
            END
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS trg_audit_logs_no_delete
            BEFORE DELETE ON audit_logs
            BEGIN
                SELECT RAISE(ABORT, 'audit_logs is append-only');
            END
            """
        )
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            """
            CREATE OR REPLACE FUNCTION guardian_prevent_audit_log_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'audit_logs is append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS trg_audit_logs_no_update ON audit_logs")
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS trg_audit_logs_no_delete ON audit_logs")
        connection.exec_driver_sql(
            """
            CREATE TRIGGER trg_audit_logs_no_update
            BEFORE UPDATE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION guardian_prevent_audit_log_mutation()
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TRIGGER trg_audit_logs_no_delete
            BEFORE DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION guardian_prevent_audit_log_mutation()
            """
        )


event.listen(AuditLog.__table__, "after_create", _create_audit_append_only_triggers)


@event.listens_for(Session, "before_flush")
def _seal_and_protect_audit_events(session: Session, _flush_context, _instances) -> None:
    for obj in tuple(session.deleted):
        if isinstance(obj, AuditLog):
            raise AuditLogMutationError("Audit events are append-only and cannot be deleted.")
    for obj in tuple(session.dirty):
        if isinstance(obj, AuditLog) and session.is_modified(obj, include_collections=True):
            raise AuditLogMutationError("Audit events are append-only and cannot be updated.")

    pending = [obj for obj in tuple(session.new) if isinstance(obj, AuditLog)]
    if not pending:
        return

    grouped: dict[str, list[AuditLog]] = {}
    for audit_event in pending:
        scope_key = audit_scope_key(audit_event.organization_id)
        grouped.setdefault(scope_key, []).append(audit_event)

    connection = session.connection()
    head_table = AuditLogChainHead.__table__
    for scope_key in sorted(grouped):
        if connection.dialect.name == "postgresql":
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": advisory_lock_id(scope_key)},
            )

        head = connection.execute(
            select(head_table.c.last_sequence, head_table.c.last_hash)
            .where(head_table.c.scope_key == scope_key)
            .with_for_update()
        ).first()
        sequence = int(head.last_sequence) if head else 0
        previous_hash = head.last_hash if head else GENESIS_HASH
        now = utc_naive()

        for audit_event in grouped[scope_key]:
            sequence += 1
            created_at = utc_naive(audit_event.created_at or now)
            audit_event.created_at = created_at
            audit_event.updated_at = audit_event.updated_at or created_at
            audit_event.scope_key = scope_key
            audit_event.sequence_number = sequence
            audit_event.previous_hash = previous_hash
            audit_event.event_version = AUDIT_EVENT_VERSION
            audit_event.event_hash = compute_audit_event_hash(
                scope_key=scope_key,
                sequence_number=sequence,
                previous_hash=previous_hash,
                organization_id=audit_event.organization_id,
                user_id=audit_event.user_id,
                action=audit_event.action,
                entity_type=audit_event.entity_type,
                entity_id=audit_event.entity_id,
                ip_address=audit_event.ip_address,
                details=audit_event.details,
                created_at=created_at,
                event_version=AUDIT_EVENT_VERSION,
            )
            previous_hash = audit_event.event_hash

        if head:
            connection.execute(
                update(head_table)
                .where(head_table.c.scope_key == scope_key)
                .values(last_sequence=sequence, last_hash=previous_hash, updated_at=now)
            )
        else:
            connection.execute(
                insert(head_table).values(
                    scope_key=scope_key,
                    last_sequence=sequence,
                    last_hash=previous_hash,
                    updated_at=now,
                )
            )


_USER_SECURITY_FIELDS = (
    "role",
    "hashed_password",
    "is_active",
    "organization_id",
    "email",
)


@event.listens_for(User, "before_update")
def _mark_user_security_change(_mapper, _connection, target: User) -> None:
    state = inspect(target)
    changed_fields = tuple(
        field_name
        for field_name in _USER_SECURITY_FIELDS
        if state.attrs[field_name].history.has_changes()
    )
    if not changed_fields:
        return

    target.security_version = int(target.security_version or 1) + 1
    target.security_changed_at = datetime.utcnow()
    target.__dict__["_pending_security_change_fields"] = changed_fields


@event.listens_for(User, "after_update")
def _revoke_sessions_after_user_security_change(_mapper, connection, target: User) -> None:
    changed_fields = target.__dict__.pop("_pending_security_change_fields", ())
    if not changed_fields:
        return

    connection.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == target.id,
            AuthSession.revoked_at.is_(None),
        )
        .values(
            revoked_at=datetime.utcnow(),
            revocation_reason="user_security_state_changed",
        )
    )


@event.listens_for(Organization, "before_update")
def _mark_organization_deactivation(_mapper, _connection, target: Organization) -> None:
    state = inspect(target)
    if state.attrs.is_active.history.has_changes() and not target.is_active:
        target.__dict__["_pending_session_revocation"] = True


@event.listens_for(Organization, "after_update")
def _revoke_sessions_after_organization_deactivation(
    _mapper,
    connection,
    target: Organization,
) -> None:
    if not target.__dict__.pop("_pending_session_revocation", False):
        return

    user_ids = select(User.id).where(User.organization_id == target.id)
    connection.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id.in_(user_ids),
            AuthSession.revoked_at.is_(None),
        )
        .values(
            revoked_at=datetime.utcnow(),
            revocation_reason="organization_deactivated",
        )
    )
