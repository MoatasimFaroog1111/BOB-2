import { API_BASE_URL } from "@/lib/api";

export interface DocumentsGateway {
  parseManualText(init: RequestInit): Promise<Response>;
  chatSpreadsheet(init: RequestInit): Promise<Response>;
  uploadDocuments(init: RequestInit): Promise<Response>;
  parseBankStatement(init: RequestInit): Promise<Response>;
  prepareDailyBankReview(init: RequestInit): Promise<Response>;
  submitDailyBankReview(init: RequestInit): Promise<Response>;
  proposeTransaction(init: RequestInit): Promise<Response>;
  loadDiscovery(): Promise<Response>;
  loadPartners(companyQuery: string): Promise<Response>;
  loadAnalyticAccounts(companyQuery: string): Promise<Response>;
  loadJournals(companyQuery: string): Promise<Response>;
  registerDocument(init: RequestInit): Promise<Response>;
}

class HttpDocumentsGateway implements DocumentsGateway {
  private request(path: string, init?: RequestInit): Promise<Response> {
    return fetch(`${API_BASE_URL}${path}`, init);
  }

  parseManualText(init: RequestInit) { return this.request("/api/v1/erp/parse-manual-text", init); }
  chatSpreadsheet(init: RequestInit) { return this.request("/api/v1/erp/chat-spreadsheet", init); }
  uploadDocuments(init: RequestInit) { return this.request("/api/v1/erp/upload-documents", init); }
  parseBankStatement(init: RequestInit) { return this.request("/api/v1/erp/bank-statement-parse", init); }
  prepareDailyBankReview(init: RequestInit) { return this.request("/api/v1/erp/daily-bank-review/prepare", init); }
  submitDailyBankReview(init: RequestInit) { return this.request("/api/v1/erp/daily-bank-review/submit", init); }
  proposeTransaction(init: RequestInit) { return this.request("/api/v1/erp/propose-transaction", init); }
  loadDiscovery() { return this.request("/api/v1/erp/discovery"); }
  loadPartners(query: string) { return this.request(`/api/v1/erp/partners${query}`); }
  loadAnalyticAccounts(query: string) { return this.request(`/api/v1/erp/analytic-accounts${query}`); }
  loadJournals(query: string) { return this.request(`/api/v1/erp/journals${query}`); }
  registerDocument(init: RequestInit) { return this.request("/api/v1/erp/register-document", init); }
}

export const documentsGateway: DocumentsGateway = new HttpDocumentsGateway();
