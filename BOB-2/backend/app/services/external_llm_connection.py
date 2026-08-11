"""Application service for tenant-scoped external LLM connection diagnostics."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.external_llm import ExternalLLMPolicy
from app.services.external_llm_gateway import ExternalLLMGateway, ExternalLLMRequestContext
from app.services.secret_store import get_tenant_secret


def test_external_llm_connection(db: Session, *, organization_id: int, user_id: int) -> dict[str, object]:
    policy = (
        db.query(ExternalLLMPolicy)
        .filter(ExternalLLMPolicy.organization_id == organization_id)
        .first()
    )
    if policy is None or not policy.approved_provider or not policy.approved_model:
        raise ValueError("Save an external AI provider and model policy before testing.")
    api_key = get_tenant_secret(db, organization_id=organization_id, purpose="external_llm_api_key")
    context = ExternalLLMRequestContext(
        organization_id=organization_id,
        user_id=user_id,
        purpose="accounting_reasoning",
        source_type="connection_test",
        request_id=f"llm-test-{uuid4().hex}",
    )
    gateway = ExternalLLMGateway(
        db=db,
        context=context,
        provider=policy.approved_provider,
        model=policy.approved_model,
        api_key=api_key,
    )
    gateway.execute_chat_completion(
        system_prompt="Return only a JSON object with the key status and value ok.",
        structured_payload={"connection_test": True},
        temperature=0,
    )
    return {
        "connected": True,
        "provider": policy.approved_provider,
        "model": policy.approved_model,
    }
