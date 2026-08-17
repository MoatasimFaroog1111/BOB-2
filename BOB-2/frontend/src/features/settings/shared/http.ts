import { API_BASE_URL } from "@/lib/api";

export class SettingsApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly details: unknown = null,
  ) {
    super(message);
    this.name = "SettingsApiError";
  }
}

async function parseResponseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json().catch(() => null);
  }
  return response.text().catch(() => null);
}

async function checkedJson<T>(response: Response, fallbackLabel: string): Promise<T> {
  const body = await parseResponseBody(response);
  if (!response.ok) {
    let detail = "";
    if (typeof body === "object" && body !== null && "detail" in body) {
      const raw = (body as { detail?: unknown }).detail;
      if (typeof raw === "string") {
        detail = raw;
      } else if (raw && typeof raw === "object" && "message" in raw) {
        detail = String((raw as { message?: unknown }).message || "");
      } else if (raw != null) {
        detail = JSON.stringify(raw);
      }
    }
    throw new SettingsApiError(
      detail || `${fallbackLabel} failed with status ${response.status}.`,
      response.status,
      body,
    );
  }
  return body as T;
}

export async function requestJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
    cache: init.cache ?? "no-store",
  });
  return checkedJson<T>(response, "Settings request");
}

export async function requestFormJson<T>(
  path: string,
  form: FormData,
  init: Omit<RequestInit, "body"> = {},
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    method: init.method ?? "POST",
    body: form,
    cache: init.cache ?? "no-store",
  });
  return checkedJson<T>(response, "Multipart settings request");
}
