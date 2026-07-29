const CHAT_SPREADSHEET_PATH = "/api/v1/erp/chat-spreadsheet";
const INSTALL_MARKER = "__bobCompanyAwareFetchInstalled";

function selectedCompanyId(): number | null {
  if (typeof window === "undefined") return null;
  const value = window.localStorage.getItem("selectedCompanyId");
  if (!value) return null;
  const parsed = Number.parseInt(value, 10);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

/**
 * Inject the selected Odoo company into spreadsheet-chat POST bodies.
 *
 * The legacy documents page uses the browser fetch API directly in several
 * places. Keeping this narrowly scoped transport middleware here avoids
 * duplicating company-selection logic and affects only one explicit endpoint.
 */
export function installCompanyAwareFetch(): void {
  if (typeof window === "undefined") return;

  const markedWindow = window as typeof window & Record<string, unknown>;
  if (markedWindow[INSTALL_MARKER]) return;

  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const isChatRequest = url.includes(CHAT_SPREADSHEET_PATH);
    const isJsonBody = typeof init?.body === "string";

    if (isChatRequest && isJsonBody) {
      try {
        const body = JSON.parse(init.body as string) as Record<string, unknown>;
        if (body.company_id == null) {
          const companyId = selectedCompanyId();
          if (companyId !== null) {
            body.company_id = companyId;
            init = { ...init, body: JSON.stringify(body) };
          }
        }
      } catch {
        // Preserve the original request when its body is not valid JSON.
      }
    }

    return originalFetch(input, init);
  };

  markedWindow[INSTALL_MARKER] = true;
}
