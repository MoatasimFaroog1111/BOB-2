from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.core.config import settings

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


class LLMAccountingReasoner:
    """Optional real LLM layer for the accounting multi-agent workflow.

    The rule-based agents always run first. This service then asks an external
    OpenAI-compatible chat-completions API for senior accounting reasoning only
    when an API key is configured. Without a key it returns an explicit disabled
    status; it does not fake or simulate LLM output.
    """

    def __init__(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        api_url: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.provider = provider or getattr(settings, "ACCOUNTING_LLM_PROVIDER", "deepseek")
        self.model = model or getattr(settings, "ACCOUNTING_LLM_MODEL", "deepseek-chat")
        self.api_key = api_key if api_key is not None else self._resolve_api_key(self.provider)
        self.api_url = api_url or getattr(settings, "ACCOUNTING_LLM_API_URL", "https://api.deepseek.com/chat/completions")
        self.timeout_seconds = timeout_seconds or getattr(settings, "ACCOUNTING_LLM_TIMEOUT_SECONDS", 45)

    def analyze(
        self,
        *,
        text: str,
        source_type: str,
        extracted_signals: dict[str, Any],
        agent_findings: list[dict[str, Any]],
        conflicts: list[dict[str, Any]],
        final_recommendation: dict[str, Any],
    ) -> LLMReasoningResult:
        if not self.api_key:
            return LLMReasoningResult(
                status="disabled_no_api_key",
                provider=self.provider,
                model=self.model,
                reasoning=None,
                error="Set DEEPSEEK_API_KEY or ACCOUNTING_LLM_API_KEY to enable real LLM accounting reasoning.",
            )

        request_payload = self._build_request_payload(
            text=text,
            source_type=source_type,
            extracted_signals=extracted_signals,
            agent_findings=agent_findings,
            conflicts=conflicts,
            final_recommendation=final_recommendation,
        )

        try:
            response_payload = self._post_chat_completion(request_payload)
            content = response_payload["choices"][0]["message"]["content"]
            reasoning = self._parse_json_content(content)
            reasoning = self._validate_reasoning(reasoning)
            return LLMReasoningResult(
                status="success",
                provider=self.provider,
                model=self.model,
                reasoning=reasoning,
            )
        except Exception as exc:
            logger.warning("LLM accounting reasoning failed: %s", exc)
            return LLMReasoningResult(
                status="failed",
                provider=self.provider,
                model=self.model,
                reasoning=None,
                error=str(exc),
            )

    def _build_request_payload(
        self,
        *,
        text: str,
        source_type: str,
        extracted_signals: dict[str, Any],
        agent_findings: list[dict[str, Any]],
        conflicts: list[dict[str, Any]],
        final_recommendation: dict[str, Any],
    ) -> dict[str, Any]:
        user_payload = {
            "source_type": source_type,
            "document_text": text[:8000],
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
        return {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
        }

    def _post_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.api_url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"LLM provider HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM provider connection failed: {exc.reason}") from exc
        return json.loads(raw)

    @staticmethod
    def _parse_json_content(content: str) -> dict[str, Any]:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
            cleaned = re.sub(r"```$", "", cleaned).strip()
        return json.loads(cleaned)

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

    @staticmethod
    def _resolve_api_key(provider: str) -> str:
        explicit = getattr(settings, "ACCOUNTING_LLM_API_KEY", "") or os.getenv("ACCOUNTING_LLM_API_KEY", "")
        if explicit:
            return explicit
        provider_name = provider.lower().strip()
        if provider_name == "deepseek":
            return getattr(settings, "DEEPSEEK_API_KEY", "") or os.getenv("DEEPSEEK_API_KEY", "")
        if provider_name == "openai":
            return os.getenv("OPENAI_API_KEY", "")
        return os.getenv("ACCOUNTING_LLM_API_KEY", "")
