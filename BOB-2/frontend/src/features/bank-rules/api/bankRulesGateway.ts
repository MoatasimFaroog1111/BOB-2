import { API_BASE_URL } from "@/lib/api";

interface BankRuleReferenceCatalog {
  journals?: unknown[];
  accounts?: unknown[];
  partners?: unknown[];
  analytic_accounts?: unknown[];
}

class BankRulesGateway {
  private referenceCatalogPromise: Promise<BankRuleReferenceCatalog> | null = null;

  listRules(journalId?: number): Promise<Response> {
    const query = journalId ? `?journal_id=${encodeURIComponent(String(journalId))}` : "";
    return fetch(`${API_BASE_URL}/api/v1/erp/bank-rules${query}`, { cache: "no-store" });
  }

  private loadReferenceCatalog(): Promise<BankRuleReferenceCatalog> {
    if (!this.referenceCatalogPromise) {
      this.referenceCatalogPromise = fetch(
        `${API_BASE_URL}/api/v1/erp/bank-rules/reference-catalog`,
        { cache: "no-store" },
      )
        .then(async (response) => {
          if (!response.ok) {
            throw new Error(await response.text());
          }
          return response.json() as Promise<BankRuleReferenceCatalog>;
        })
        .catch((error) => {
          // A transient Odoo 429 must be retryable on the next user/page attempt.
          this.referenceCatalogPromise = null;
          throw error;
        });
    }
    return this.referenceCatalogPromise;
  }

  private catalogSlice(key: keyof BankRuleReferenceCatalog): Promise<Response> {
    return this.loadReferenceCatalog()
      .then((catalog) => new Response(JSON.stringify(catalog[key] || []), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }))
      .catch((error) => new Response(
        JSON.stringify({ detail: error instanceof Error ? error.message : String(error) }),
        { status: 503, headers: { "Content-Type": "application/json" } },
      ));
  }

  referenceCatalog(): Promise<BankRuleReferenceCatalog> {
    return this.loadReferenceCatalog();
  }

  listJournals(): Promise<Response> {
    return this.catalogSlice("journals");
  }

  listAccounts(): Promise<Response> {
    return this.catalogSlice("accounts");
  }

  listPartners(): Promise<Response> {
    return this.catalogSlice("partners");
  }

  listAnalyticAccounts(): Promise<Response> {
    return this.catalogSlice("analytic_accounts");
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
