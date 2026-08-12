import { API_BASE_URL } from "@/lib/api";

class BankRulesGateway {
  listRules(journalId?: number): Promise<Response> {
    const query = journalId ? `?journal_id=${encodeURIComponent(String(journalId))}` : "";
    return fetch(`${API_BASE_URL}/api/v1/erp/bank-rules${query}`, { cache: "no-store" });
  }

  listJournals(): Promise<Response> {
    return fetch(`${API_BASE_URL}/api/v1/erp/journals`, { cache: "no-store" });
  }

  listAccounts(): Promise<Response> {
    return fetch(`${API_BASE_URL}/api/v1/erp/accounts`, { cache: "no-store" });
  }

  listPartners(): Promise<Response> {
    return fetch(`${API_BASE_URL}/api/v1/erp/partners`, { cache: "no-store" });
  }

  listAnalyticAccounts(): Promise<Response> {
    return fetch(`${API_BASE_URL}/api/v1/erp/analytic-accounts`, { cache: "no-store" });
  }

  createRule(payload: unknown): Promise<Response> {
    return fetch(`${API_BASE_URL}/api/v1/erp/bank-rules`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  createVersion(ruleId: number, payload: unknown): Promise<Response> {
    return fetch(`${API_BASE_URL}/api/v1/erp/bank-rules/${ruleId}/versions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  editDraft(ruleId: number, payload: unknown): Promise<Response> {
    return fetch(`${API_BASE_URL}/api/v1/erp/bank-rules/${ruleId}/draft`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  approve(ruleId: number, versionId: number, approvalNote = ""): Promise<Response> {
    return fetch(`${API_BASE_URL}/api/v1/erp/bank-rules/${ruleId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version_id: versionId, approval_note: approvalNote }),
    });
  }

  disable(ruleId: number, reason = ""): Promise<Response> {
    return fetch(`${API_BASE_URL}/api/v1/erp/bank-rules/${ruleId}/disable`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    });
  }

  importFromOdoo(journalId: number): Promise<Response> {
    return fetch(`${API_BASE_URL}/api/v1/erp/bank-rules/import-odoo`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ journal_id: journalId }),
    });
  }

  testRule(ruleId: number, statement: File): Promise<Response> {
    const data = new FormData();
    data.append("statement", statement);
    return fetch(`${API_BASE_URL}/api/v1/erp/bank-rules/${ruleId}/test`, {
      method: "POST",
      body: data,
    });
  }
}

export const bankRulesGateway = new BankRulesGateway();
