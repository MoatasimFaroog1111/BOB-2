import { describe, expect, it } from "vitest";

import { publicApiErrorMessage } from "./publicApiError";

describe("publicApiErrorMessage", () => {
  it("maps the AI unavailable contract without exposing provider configuration", async () => {
    const response = new Response(
      JSON.stringify({
        detail: {
          code: "ai_provider_unavailable",
          message: "AI assistant is temporarily unavailable.",
        },
      }),
      { status: 503, headers: { "Content-Type": "application/json" } },
    );

    await expect(publicApiErrorMessage(response, "ar")).resolves.toBe(
      "المساعد الذكي غير متاح مؤقتًا. حاول لاحقًا أو تواصل مع مسؤول النظام.",
    );
  });

  it("never displays an untrusted backend error body", async () => {
    const response = new Response(
      JSON.stringify({
        detail: "Set ANTHROPIC_API_KEY or start Ollama locally",
      }),
      { status: 500, headers: { "Content-Type": "application/json" } },
    );

    const message = await publicApiErrorMessage(response, "en");

    expect(message).toBe("The service could not complete the request. Please try again.");
    expect(message).not.toContain("ANTHROPIC");
    expect(message).not.toContain("Ollama");
  });
});
