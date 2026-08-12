from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SpreadsheetPromptRoute(str, Enum):
    """High-level destination for a spreadsheet prompt."""

    ASSISTANT = "assistant"
    COMMAND = "command"
    EXISTING_PIPELINE = "existing_pipeline"


@dataclass(frozen=True, slots=True)
class SpreadsheetRoutingDecision:
    route: SpreadsheetPromptRoute
    reason: str


class SpreadsheetPromptRoutingPolicy:
    """Classify read/analysis prompts separately from mutating accounting commands.

    This policy deliberately does not execute anything. Its only responsibility is deciding
    which existing application component should receive the prompt. Keeping that decision in
    one small component prevents the command model from interpreting analytical questions as
    draft mutations and keeps the HTTP router focused on orchestration.
    """

    _NO_MUTATION_PHRASES = (
        "بدون تعديل",
        "دون تعديل",
        "من دون تعديل",
        "لا تعدل",
        "لا تعدّل",
        "لا تغير",
        "لا تغيّر",
        "without modifying",
        "without changing",
        "do not modify",
        "don't modify",
        "do not change",
        "don't change",
    )

    _ANALYSIS_MARKERS = (
        "ما هو",
        "ما هي",
        "ما الحساب",
        "أي حساب",
        "اي حساب",
        "اذكر",
        "لماذا",
        "اشرح",
        "فسر",
        "فسّر",
        "حلل",
        "حلّل",
        "هل ",
        "كيف ",
        "what is",
        "what are",
        "which account",
        "which ",
        "list ",
        "why ",
        "explain",
        "analyze",
        "analyse",
        "how ",
        "can you",
        "could you",
    )

    _COMMAND_MARKERS = (
        "ضع",
        "غيّر",
        "غير",
        "عدّل",
        "عدل",
        "احذف",
        "حذف",
        "سجل",
        "سجّل",
        "أنشئ",
        "انشئ",
        "رحّل",
        "رحل",
        "اعتمد",
        "استبدل",
        "صحح",
        "صحّح",
        "set ",
        "change ",
        "update ",
        "edit ",
        "delete ",
        "remove ",
        "record ",
        "create ",
        "post ",
        "approve ",
        "replace ",
        "fix ",
    )

    @staticmethod
    def _normalize(prompt: str) -> str:
        return " ".join((prompt or "").strip().lower().split())

    @staticmethod
    def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
        return any(marker in text for marker in markers)

    def decide(self, prompt: str) -> SpreadsheetRoutingDecision:
        text = self._normalize(prompt)
        if not text:
            return SpreadsheetRoutingDecision(
                SpreadsheetPromptRoute.EXISTING_PIPELINE,
                "empty prompt",
            )

        # A negative mutation instruction must win over the word "تعديل/change" inside it.
        if self._contains_any(text, self._NO_MUTATION_PHRASES):
            return SpreadsheetRoutingDecision(
                SpreadsheetPromptRoute.ASSISTANT,
                "explicit read-only/no-mutation request",
            )

        if (
            self._contains_any(text, self._ANALYSIS_MARKERS)
            or text.endswith("؟")
            or text.endswith("?")
        ):
            return SpreadsheetRoutingDecision(
                SpreadsheetPromptRoute.ASSISTANT,
                "analytical or informational question",
            )

        if self._contains_any(text, self._COMMAND_MARKERS):
            return SpreadsheetRoutingDecision(
                SpreadsheetPromptRoute.COMMAND,
                "explicit mutation/execution command",
            )

        return SpreadsheetRoutingDecision(
            SpreadsheetPromptRoute.EXISTING_PIPELINE,
            "no explicit analysis or mutation signal",
        )


spreadsheet_prompt_routing_policy = SpreadsheetPromptRoutingPolicy()
