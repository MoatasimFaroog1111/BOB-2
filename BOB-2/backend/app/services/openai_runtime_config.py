"""Resolve the local-first OpenAI fallback configuration for the active tenant.

This module owns configuration lookup only. The OpenAI transport remains isolated in
``openai_fallback_provider`` and depends on the small configuration-source contract.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Callable, Protocol

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.external_llm import ExternalLLMPolicy
from app.security.tenant_scope import current_organization_id
from app.services.external_llm_gateway import ALLOWED_RETENTION_MODES
from app.services.openai_fallback_provider import (
    EnvironmentOpenAIFallbackConfigSource,
    OpenAIFallbackConfig,
    OpenAIFallbackConfigSource,
)
from app.services.secret_provider_types import SecretNotConfigured, SecretStoreError
from app.services.secret_store import get_tenant_secret

logger = logging.getLogger(__name__)


def _csv_items(value: str) -> set[str]:
    return {item.strip().lower() for item in value.split(",") if item.strip()}


@dataclass(frozen=True, slots=True)
class TenantOpenAISelection:
    api_key: str
    model: str


class TenantOpenAISettingsResolver(Protocol):
    """Small interface for resolving one tenant's approved OpenAI selection."""

    def resolve(self, organization_id: int) -> TenantOpenAISelection | None: ...


class SqlAlchemyTenantOpenAISettingsResolver:
    """Read the active tenant policy and key without leaking either to callers."""

    def __init__(self, session_factory: Callable[[], Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    def resolve(self, organization_id: int) -> TenantOpenAISelection | None:
        db = self._session_factory()
        try:
            policy = (
                db.query(ExternalLLMPolicy)
                .filter(ExternalLLMPolicy.organization_id == organization_id)
                .first()
            )
            if not self._is_authorized(policy):
                return None
            try:
                api_key = get_tenant_secret(
                    db,
                    organization_id=organization_id,
                    purpose="external_llm_api_key",
                )
            except (SecretNotConfigured, SecretStoreError):
                logger.info(
                    "Tenant OpenAI fallback credential is unavailable",
                    extra={"organization_id": organization_id},
                )
                return None
            model = (policy.approved_model or "").strip()
            return TenantOpenAISelection(api_key=api_key, model=model)
        finally:
            db.close()

    @staticmethod
    def _is_authorized(policy: ExternalLLMPolicy | None) -> bool:
        if policy is None:
            return False
        provider = (policy.approved_provider or "").strip().lower()
        model = (policy.approved_model or "").strip()
        allowed_providers = _csv_items(settings.EXTERNAL_LLM_ALLOWED_PROVIDERS)
        allowed_models = _csv_items(settings.EXTERNAL_LLM_ALLOWED_MODELS)
        return bool(
            policy.external_llm_enabled
            and provider == "openai"
            and provider in allowed_providers
            and model
            and f"{provider}:{model}".lower() in allowed_models
            and bool(policy.allowed_purposes)
            and policy.dpa_version == settings.EXTERNAL_LLM_REQUIRED_DPA_VERSION
            and policy.dpa_reference
            and policy.data_residency_region
            and policy.provider_retention_mode in ALLOWED_RETENTION_MODES
            and policy.accepted_at
            and policy.accepted_by_user_id
            and policy.revoked_at is None
        )


class TenantAwareOpenAIConfigSource:
    """Prefer UI-managed tenant settings whenever a request tenant is active.

    Deployment variables still own endpoint allowlisting, network limits, and the two
    global kill switches. For a tenant-bound request, an environment API key is never
    used as a substitute for a missing tenant credential.
    """

    def __init__(
        self,
        deployment_source: OpenAIFallbackConfigSource | None = None,
        tenant_settings: TenantOpenAISettingsResolver | None = None,
        tenant_id_resolver: Callable[[], int | None] | None = None,
    ) -> None:
        self._deployment_source = (
            deployment_source or EnvironmentOpenAIFallbackConfigSource()
        )
        self._tenant_settings = (
            tenant_settings or SqlAlchemyTenantOpenAISettingsResolver()
        )
        self._tenant_id_resolver = tenant_id_resolver or (
            lambda: current_organization_id(required=False)
        )

    def load(self) -> OpenAIFallbackConfig:
        deployment = self._deployment_source.load()
        organization_id = self._tenant_id_resolver()

        # Preserve the explicitly configured deployment-only behavior for background
        # processes that do not execute inside an authenticated tenant scope.
        if organization_id is None:
            return deployment

        globally_enabled = bool(
            deployment.enabled and settings.EXTERNAL_LLM_ENABLED
        )
        if not globally_enabled:
            return replace(deployment, enabled=False, api_key="")

        selection = self._tenant_settings.resolve(organization_id)
        if selection is None:
            return replace(deployment, enabled=False, api_key="")

        return replace(
            deployment,
            enabled=True,
            api_key=selection.api_key,
            model=selection.model,
        )
