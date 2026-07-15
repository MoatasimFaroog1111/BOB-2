from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.models.core import AuditLog, Organization, User
from app.models.external_llm import ExternalLLMPolicy
from app.security.dependencies import require_permission
from app.services.external_llm_gateway import (
    ALLOWED_EXTERNAL_LLM_PURPOSES,
    ALLOWED_RETENTION_MODES,
)
from app.services.secret_store import (
    SecretStoreError,
    binding_status,
    put_tenant_secret,
    revoke_tenant_secret,
    secret_is_configured,
)

router = APIRouter()


def _csv_items(value: str) -> list[str]:
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def _organization_context(db: Session, token_payload: dict) -> tuple[int, int]:
    organization_id = token_payload.get("organization_id")
    user_id = token_payload.get("user_id")
    if not isinstance(organization_id, int) or organization_id <= 0:
        raise HTTPException(status_code=403, detail="The authenticated user is not assigned to an organization.")
    if not isinstance(user_id, int) or user_id <= 0:
        raise HTTPException(status_code=401, detail="The authenticated user identity is incomplete.")
    organization = db.query(Organization).filter(Organization.id == organization_id).first()
    user = db.query(User).filter(User.id == user_id).first()
    if organization is None or not organization.is_active:
        raise HTTPException(status_code=403, detail="The organization is inactive.")
    if user is None or not user.is_active or user.organization_id != organization_id:
        raise HTTPException(status_code=403, detail="The user is not active in this organization.")
    return organization_id, user_id


class ExternalLLMPolicyUpdate(BaseModel):
    external_llm_enabled: bool
    approved_provider: str | None = Field(default=None, max_length=100)
    approved_model: str | None = Field(default=None, max_length=200)
    allowed_purposes: list[str] = Field(default_factory=list, max_length=10)
    allow_redacted_document_text: bool = False
    allow_financial_values: bool = False
    max_redacted_text_chars: int = Field(default=0, ge=0, le=8_000)
    dpa_version: str | None = Field(default=None, max_length=100)
    dpa_reference: str | None = Field(default=None, max_length=255)
    data_residency_region: str | None = Field(default=None, max_length=100)
    provider_retention_mode: str | None = Field(default=None, max_length=100)
    accept_dpa: bool = False

    @field_validator(
        "approved_provider",
        "approved_model",
        "dpa_version",
        "dpa_reference",
        "data_residency_region",
        "provider_retention_mode",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: Any):
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("allowed_purposes")
    @classmethod
    def normalize_purposes(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            item = value.strip().lower()
            if item and item not in normalized:
                normalized.append(item)
        return normalized


class ExternalLLMKeyPayload(BaseModel):
    api_key: str = Field(min_length=20, max_length=4096)


class ExternalLLMDisclosureEvent(BaseModel):
    id: int
    action: str
    request_id: str | None
    user_id: int | None
    details: dict[str, Any]
    created_at: datetime


def _effective_enabled(policy: ExternalLLMPolicy | None, key_configured: bool) -> bool:
    if policy is None:
        return False
    provider = (policy.approved_provider or "").strip().lower()
    model = (policy.approved_model or "").strip()
    return bool(
        settings.EXTERNAL_LLM_ENABLED
        and key_configured
        and policy.external_llm_enabled
        and provider in set(_csv_items(settings.EXTERNAL_LLM_ALLOWED_PROVIDERS))
        and f"{provider}:{model}".lower() in set(_csv_items(settings.EXTERNAL_LLM_ALLOWED_MODELS))
        and bool(policy.allowed_purposes)
        and set(policy.allowed_purposes or []).issubset(ALLOWED_EXTERNAL_LLM_PURPOSES)
        and policy.dpa_version == settings.EXTERNAL_LLM_REQUIRED_DPA_VERSION
        and policy.dpa_reference
        and policy.data_residency_region
        and policy.provider_retention_mode in ALLOWED_RETENTION_MODES
        and policy.accepted_at
        and policy.accepted_by_user_id
        and policy.revoked_at is None
        and policy.max_redacted_text_chars <= settings.EXTERNAL_LLM_MAX_REDACTED_TEXT_CHARS
    )


def _credential_response(db: Session, organization_id: int) -> dict[str, Any]:
    binding = binding_status(db, organization_id=organization_id, purpose="external_llm_api_key")
    return {
        "configured": bool(binding and binding.status == "active" and binding.revoked_at is None),
        "storage": "central_secret_store",
        "provider": binding.provider if binding else None,
        "status": binding.status if binding else None,
        "version_fingerprint": binding.fingerprint_sha256[:12] if binding else None,
        "last_rotated_at": binding.last_rotated_at if binding else None,
    }


def _policy_response(db: Session, policy: ExternalLLMPolicy | None, organization_id: int) -> dict[str, Any]:
    allowed_providers = _csv_items(settings.EXTERNAL_LLM_ALLOWED_PROVIDERS)
    allowed_models = _csv_items(settings.EXTERNAL_LLM_ALLOWED_MODELS)
    key_configured = secret_is_configured(
        db,
        organization_id=organization_id,
        purpose="external_llm_api_key",
    )
    return {
        "organization_id": organization_id,
        "global_enabled": settings.EXTERNAL_LLM_ENABLED,
        "api_key_configured": key_configured,
        "credential": _credential_response(db, organization_id),
        "effective_enabled": _effective_enabled(policy, key_configured),
        "required_dpa_version": settings.EXTERNAL_LLM_REQUIRED_DPA_VERSION,
        "globally_allowed_providers": allowed_providers,
        "globally_allowed_models": allowed_models,
        "available_purposes": sorted(ALLOWED_EXTERNAL_LLM_PURPOSES),
        "available_retention_modes": sorted(ALLOWED_RETENTION_MODES),
        "global_max_redacted_text_chars": settings.EXTERNAL_LLM_MAX_REDACTED_TEXT_CHARS,
        "policy": None
        if policy is None
        else {
            "id": policy.id,
            "external_llm_enabled": policy.external_llm_enabled,
            "approved_provider": policy.approved_provider,
            "approved_model": policy.approved_model,
            "allowed_purposes": policy.allowed_purposes or [],
            "allow_redacted_document_text": policy.allow_redacted_document_text,
            "allow_financial_values": policy.allow_financial_values,
            "max_redacted_text_chars": policy.max_redacted_text_chars,
            "dpa_version": policy.dpa_version,
            "dpa_reference": policy.dpa_reference,
            "data_residency_region": policy.data_residency_region,
            "provider_retention_mode": policy.provider_retention_mode,
            "accepted_by_user_id": policy.accepted_by_user_id,
            "accepted_at": policy.accepted_at,
            "revoked_by_user_id": policy.revoked_by_user_id,
            "revoked_at": policy.revoked_at,
            "last_reviewed_at": policy.last_reviewed_at,
            "policy_version": policy.policy_version,
            "created_at": policy.created_at,
            "updated_at": policy.updated_at,
        },
    }


def _validate_enable_request(
    db: Session,
    organization_id: int,
    payload: ExternalLLMPolicyUpdate,
    current: ExternalLLMPolicy | None,
) -> bool:
    if not payload.external_llm_enabled:
        return False
    if not secret_is_configured(db, organization_id=organization_id, purpose="external_llm_api_key"):
        raise HTTPException(status_code=400, detail="Configure the tenant external AI credential before enabling the policy.")
    allowed_providers = set(_csv_items(settings.EXTERNAL_LLM_ALLOWED_PROVIDERS))
    allowed_models = set(_csv_items(settings.EXTERNAL_LLM_ALLOWED_MODELS))
    purposes = set(payload.allowed_purposes)
    if not payload.approved_provider or payload.approved_provider.lower() not in allowed_providers:
        raise HTTPException(status_code=400, detail="The selected external LLM provider is not allowed.")
    model_pair = f"{payload.approved_provider.lower()}:{payload.approved_model or ''}".lower()
    if not payload.approved_model or model_pair not in allowed_models:
        raise HTTPException(status_code=400, detail="The selected external LLM model is not allowed.")
    if not purposes or not purposes.issubset(ALLOWED_EXTERNAL_LLM_PURPOSES):
        raise HTTPException(status_code=400, detail="At least one approved external LLM purpose is required.")
    if payload.max_redacted_text_chars > settings.EXTERNAL_LLM_MAX_REDACTED_TEXT_CHARS:
        raise HTTPException(status_code=400, detail="The document-text limit exceeds the global maximum.")
    if not payload.allow_redacted_document_text and payload.max_redacted_text_chars != 0:
        raise HTTPException(status_code=400, detail="The document-text limit must be zero when text disclosure is disabled.")
    if payload.dpa_version != settings.EXTERNAL_LLM_REQUIRED_DPA_VERSION:
        raise HTTPException(status_code=400, detail="The required DPA version has not been accepted.")
    if not payload.dpa_reference or not payload.data_residency_region:
        raise HTTPException(status_code=400, detail="DPA reference and data-residency region are required.")
    if payload.provider_retention_mode not in ALLOWED_RETENTION_MODES:
        raise HTTPException(status_code=400, detail="An approved provider retention mode is required.")

    material_change = bool(
        current is None
        or not current.external_llm_enabled
        or current.revoked_at is not None
        or (current.approved_provider or "").lower() != payload.approved_provider.lower()
        or (current.approved_model or "") != payload.approved_model
        or current.dpa_version != payload.dpa_version
        or current.dpa_reference != payload.dpa_reference
        or current.data_residency_region != payload.data_residency_region
        or current.provider_retention_mode != payload.provider_retention_mode
    )
    if material_change and not payload.accept_dpa:
        raise HTTPException(status_code=400, detail="Explicit DPA acceptance is required to enable or materially change external AI processing.")
    return material_change


def _add_policy_audit(
    db: Session,
    *,
    organization_id: int,
    user_id: int,
    action: str,
    policy: ExternalLLMPolicy,
) -> None:
    db.add(
        AuditLog(
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            entity_type="external_llm_policy",
            entity_id=str(policy.id),
            details={
                "policy_version": policy.policy_version,
                "external_llm_enabled": policy.external_llm_enabled,
                "approved_provider": policy.approved_provider,
                "approved_model": policy.approved_model,
                "allowed_purposes": policy.allowed_purposes or [],
                "allow_redacted_document_text": policy.allow_redacted_document_text,
                "allow_financial_values": policy.allow_financial_values,
                "max_redacted_text_chars": policy.max_redacted_text_chars,
                "dpa_version": policy.dpa_version,
                "dpa_reference": policy.dpa_reference,
                "data_residency_region": policy.data_residency_region,
                "provider_retention_mode": policy.provider_retention_mode,
            },
        )
    )


@router.get("/credential")
def get_external_llm_credential_status(
    db: Session = Depends(get_db),
    token_payload: dict = Depends(require_permission("manage_settings")),
):
    organization_id, _ = _organization_context(db, token_payload)
    return _credential_response(db, organization_id)


@router.put("/credential")
def rotate_external_llm_credential(
    payload: ExternalLLMKeyPayload,
    db: Session = Depends(get_db),
    token_payload: dict = Depends(require_permission("manage_settings")),
):
    organization_id, user_id = _organization_context(db, token_payload)
    try:
        put_tenant_secret(
            db,
            organization_id=organization_id,
            actor_user_id=user_id,
            purpose="external_llm_api_key",
            value=payload.api_key,
        )
    except SecretStoreError as exc:
        raise HTTPException(status_code=503, detail=exc.public_message) from exc
    return _credential_response(db, organization_id)


@router.delete("/credential")
def revoke_external_llm_credential(
    db: Session = Depends(get_db),
    token_payload: dict = Depends(require_permission("manage_settings")),
):
    organization_id, user_id = _organization_context(db, token_payload)
    try:
        revoke_tenant_secret(
            db,
            organization_id=organization_id,
            actor_user_id=user_id,
            purpose="external_llm_api_key",
        )
    except SecretStoreError as exc:
        raise HTTPException(status_code=503, detail=exc.public_message) from exc
    return _credential_response(db, organization_id)


@router.get("/policy")
def get_external_llm_policy(
    db: Session = Depends(get_db),
    token_payload: dict = Depends(require_permission("manage_settings")),
):
    organization_id, _ = _organization_context(db, token_payload)
    policy = db.query(ExternalLLMPolicy).filter(ExternalLLMPolicy.organization_id == organization_id).first()
    return _policy_response(db, policy, organization_id)


@router.put("/policy")
def update_external_llm_policy(
    payload: ExternalLLMPolicyUpdate,
    db: Session = Depends(get_db),
    token_payload: dict = Depends(require_permission("manage_settings")),
):
    organization_id, user_id = _organization_context(db, token_payload)
    policy = db.query(ExternalLLMPolicy).filter(ExternalLLMPolicy.organization_id == organization_id).first()
    material_change = _validate_enable_request(db, organization_id, payload, policy)
    now = datetime.utcnow()
    created = policy is None
    if policy is None:
        policy = ExternalLLMPolicy(organization_id=organization_id, policy_version=1, allowed_purposes=[])
        db.add(policy)
        db.flush()
    else:
        policy.policy_version += 1

    policy.external_llm_enabled = payload.external_llm_enabled
    policy.approved_provider = payload.approved_provider.lower() if payload.approved_provider else None
    policy.approved_model = payload.approved_model
    policy.allowed_purposes = payload.allowed_purposes
    policy.allow_redacted_document_text = payload.allow_redacted_document_text
    policy.allow_financial_values = payload.allow_financial_values
    policy.max_redacted_text_chars = payload.max_redacted_text_chars
    policy.dpa_version = payload.dpa_version
    policy.dpa_reference = payload.dpa_reference
    policy.data_residency_region = payload.data_residency_region
    policy.provider_retention_mode = payload.provider_retention_mode
    policy.last_reviewed_at = now

    if payload.external_llm_enabled:
        if material_change or payload.accept_dpa:
            policy.accepted_by_user_id = user_id
            policy.accepted_at = now
        policy.revoked_by_user_id = None
        policy.revoked_at = None
        action = "external_llm_policy_created" if created else "external_llm_policy_enabled"
    else:
        policy.revoked_by_user_id = user_id
        policy.revoked_at = now
        action = "external_llm_policy_created_disabled" if created else "external_llm_policy_disabled"

    _add_policy_audit(db, organization_id=organization_id, user_id=user_id, action=action, policy=policy)
    try:
        db.commit()
        db.refresh(policy)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="The external AI policy could not be saved.") from exc
    return _policy_response(db, policy, organization_id)


@router.get("/disclosures", response_model=list[ExternalLLMDisclosureEvent])
def list_external_llm_disclosures(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    token_payload: dict = Depends(require_permission("view_audit_logs")),
):
    organization_id, _ = _organization_context(db, token_payload)
    rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.organization_id == organization_id,
            AuditLog.entity_type == "external_llm",
            AuditLog.action.like("external_llm_disclosure_%"),
        )
        .order_by(AuditLog.id.desc())
        .limit(limit)
        .all()
    )
    return [
        ExternalLLMDisclosureEvent(
            id=row.id,
            action=row.action,
            request_id=row.entity_id,
            user_id=row.user_id,
            details=row.details or {},
            created_at=row.created_at,
        )
        for row in rows
    ]
