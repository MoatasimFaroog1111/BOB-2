export type SupportedLanguage = "ar" | "en";

type ErrorDetail = {
  code?: unknown;
};

type ErrorEnvelope = {
  detail?: unknown;
};

const messages = {
  ar: {
    ai_provider_unavailable:
      "المساعد الذكي غير متاح مؤقتًا. حاول لاحقًا أو تواصل مع مسؤول النظام.",
    unauthorized: "انتهت الجلسة. سجّل الدخول مجددًا.",
    forbidden: "ليست لديك صلاحية لتنفيذ هذه العملية.",
    generic: "تعذر على الخدمة إكمال الطلب. حاول مرة أخرى.",
  },
  en: {
    ai_provider_unavailable:
      "The AI assistant is temporarily unavailable. Try again later or contact your administrator.",
    unauthorized: "Your session has expired. Please sign in again.",
    forbidden: "You do not have permission to perform this action.",
    generic: "The service could not complete the request. Please try again.",
  },
} as const;

function errorCode(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const detail = (payload as ErrorEnvelope).detail;
  if (!detail || typeof detail !== "object") return null;
  const code = (detail as ErrorDetail).code;
  return typeof code === "string" ? code : null;
}

/**
 * Convert an HTTP failure into an allowlisted user-facing message.
 * Backend bodies are untrusted and are never rendered directly.
 */
export async function publicApiErrorMessage(
  response: Response,
  language: SupportedLanguage,
): Promise<string> {
  const localized = messages[language];

  if (response.status === 401) return localized.unauthorized;
  if (response.status === 403) return localized.forbidden;

  let code: string | null = null;
  try {
    code = errorCode(await response.json());
  } catch {
    // Invalid/non-JSON response bodies intentionally fall through to a generic message.
  }

  if (code === "ai_provider_unavailable") {
    return localized.ai_provider_unavailable;
  }
  return localized.generic;
}
