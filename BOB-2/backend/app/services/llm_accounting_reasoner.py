from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.external_llm_gateway import (
    ExternalLLMAuditError,
    ExternalLLMGateway,
    ExternalLLMPolicyDenied,
    ExternalLLMProviderError,
    ExternalLLMRequestContext,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are GuardianAI's senior accounting, audit, VAT, and ERP review brain.
You must be conservative, audit-safe, and practical.
Never claim a journal entry is posted. Never bypass accountant approval.
Return only strict JSON with these keys:
summary, document_assessment, vat_assessment, journal_entry_recommendation, risks, questions_for_accountant, confidence_score.
"""


@dataclass
class LLMReasoningResult:
    status: str
    provider: str
    model: str
    reasoning: dict[str, Any] | None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "reasoning": self.reasoning,
            "error": self.error,
        }


GatewayFactory = Callable[..., ExternalLLMGateway]


class LLMAccountingReasoner:
    """Optional external LLM reasoning behind explicit tenant disclosure controls.

    Rule-based accounting agents remain the primary workflow. This class does not treat an
    API key as consent and cannot send data without a database session, organization, current
    user, purpose, request ID, active tenant policy, current DPA acknowledgement, redaction,
    and a committed pre-disclosure audit event.
    """

    def __init__(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        api_url: str | None = None,
        gateway_factory: GatewayFactory = ExternalLLMGateway,
    ) -> None:
        self.provider = (provider or settings.ACCOUNTING_LLM_PROVIDER).strip().lower()
        self.model = (model or settings.ACCOUNTING_LLM_MODEL).strip()
        self.api_key = api_key
        self.api_url = api_url
        self.gateway_factory = gateway_factory

    def analyze(
        self,
        *,
        text: str,
        source_type: str,
        extracted_signals: dict[str, Any],
        agent_findings: list[dict[str, Any]],
        conflicts: list[dict[str, Any]],
        final_recommendation: dict[str, Any],
        db_session: Session | None = None,
        organization_id: int | None = None,
        user_id: int | None = None,
        request_id: str | None = None,
    ) -> LLMReasoningResult:
        if (
            db_session is None
            or not isinstance(organization_id, int)
            or organization_id <= 0
            or not isinstance(user_id, int)
            or user_id <= 0
            or not request_id
        ):
            return LLMReasoningResult(
                status="disabled_no_security_context",
                provider=self.provider,
                model=self.model,
                reasoning=None,
                error="External AI reasoning requires authenticated tenant context.",
            )

        structured_payload = self._build_structured_payload(
            source_type=source_type,
            extracted_signals=extracted_signals,
            agent_findings=agent_findings,
            conflicts=conflicts,
            final_recommendation=final_recommendation,
        )
        context = ExternalLLMRequestContext(
            organization_id=organization_id,
            user_id=user_id,
            purpose="accounting_reasoning",
            source_type=source_type,
            request_id=request_id,
        )
        gateway = self.gateway_factory(
            db=db_session,
            context=context,
            provider=self.provider,
            model=self.model,
            api_key=self.api_key,
            api_url=self.api_url,
        )
        try:
            response_payload = gateway.execute_chat_completion(
                system_prompt=SYSTEM_PROMPT,
                structured_payload=structured_payload,
                raw_document_text=text,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            content = response_payload["choices"][0]["message"]["content"]
            reasoning = self._validate_reasoning(self._parse_json_content(content))
            return LLMReasoningResult(
                status="success",
                provider=self.provider,
                model=self.model,
                reasoning=reasoning,
            )
        except ExternalLLMPolicyDenied:
            logger.info("External accounting reasoning blocked by tenant disclosure policy")
            return LLMReasoningResult(
                status="blocked_by_policy",
                provider=self.provider,
                model=self.model,
                reasoning=None,
                error="External AI processing is not authorized for this organization.",
            )
        except ExternalLLMAuditError:
            logger.error("External accounting reasoning failed closed because audit persistence failed")
            return LLMReasoningResult(
                status="blocked_audit_unavailable",
                provider=self.provider,
                model=self.model,
                reasoning=None,
                error="External AI processing is unavailable because security auditing failed.",
            )
        except ExternalLLMProviderError:
            logger.warning("External accounting reasoning provider request failed")
            return LLMReasoningResult(
                status="provider_failed",
                provider=self.provider,
                model=self.model,
                reasoning=None,
                error="The external AI provider request failed.",
            )
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning("External accounting reasoning returned an invalid response shape")
            return LLMReasoningResult(
                status="invalid_provider_response",
                provider=self.provider,
                model=self.model,
                reasoning=None,
                error="The external AI provider returned an invalid response.",
            )

    @staticmethod
    def _build_structured_payload(
        *,
        source_type: str,
        extracted_signals: dict[str, Any],
        agent_findings: list[dict[str, Any]],
        conflicts: list[dict[str, Any]],
        final_recommendation: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "source_type": source_type,
            "rule_based_extracted_signals": extracted_signals,
            "rule_based_agent_findings": agent_findings,
            "rule_based_conflicts": conflicts,
            "rule_based_final_recommendation": final_recommendation,
            "required_behavior": {
                "auto_post_to_erp": False,
                "approval_required": True,
                "jurisdiction_hint": "Saudi Arabia VAT / IFRS / SOCPA where applicable",
            },
        }

    @staticmethod
    def _parse_json_content(content: str) -> dict[str, Any]:
        if not isinstance(content, str):
            raise TypeError("provider_content_not_text")
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
            cleaned = re.sub(r"```$", "", cleaned).strip()
        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            raise TypeError("provider_reasoning_not_object")
        return parsed

    @staticmethod
    def _validate_reasoning(reasoning: dict[str, Any]) -> dict[str, Any]:
        required = {
            "summary": "",
            "document_assessment": {},
            "vat_assessment": {},
            "journal_entry_recommendation": {},
            "risks": [],
            "questions_for_accountant": [],
            "confidence_score": 0.0,
        }
        for key, default_value in required.items():
            reasoning.setdefault(key, default_value)
        try:
            score = float(reasoning.get("confidence_score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        reasoning["confidence_score"] = max(0.0, min(1.0, score))
        reasoning["audit_safe"] = {"auto_posted_to_erp": False, "approval_required": True}
        return reasoning
