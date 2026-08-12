import { API_BASE_URL } from "@/lib/api";

class DailyBankAuditGateway {
  listQueue(): Promise<Response> {
    return fetch(`${API_BASE_URL}/api/v1/erp/daily-bank-review/queue`, { cache: "no-store" });
  }

  getReview(approvalId: number): Promise<Response> {
    return fetch(`${API_BASE_URL}/api/v1/erp/daily-bank-review/${approvalId}`, { cache: "no-store" });
  }

  attachSupportingDocuments(approvalId: number, files: File[]): Promise<Response> {
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));
    return fetch(`${API_BASE_URL}/api/v1/erp/daily-bank-review/${approvalId}/supporting-documents`, {
      method: "POST",
      body: formData,
    });
  }

  listSupportingDocuments(approvalId: number): Promise<Response> {
    return fetch(`${API_BASE_URL}/api/v1/erp/daily-bank-review/${approvalId}/supporting-documents`, {
      cache: "no-store",
    });
  }

  fetchSupportingDocument(approvalId: number, documentId: number): Promise<Response> {
    return fetch(`${API_BASE_URL}/api/v1/erp/daily-bank-review/${approvalId}/supporting-documents/${documentId}/content`);
  }

  runAudit(approvalId: number): Promise<Response> {
    return fetch(`${API_BASE_URL}/api/v1/erp/daily-bank-review/${approvalId}/audit`, {
      method: "POST",
    });
  }

  decide(approvalId: number, decision: "approve" | "return", note: string): Promise<Response> {
    return fetch(`${API_BASE_URL}/api/v1/erp/daily-bank-review/${approvalId}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, note }),
    });
  }

  fetchSourceDocument(documentId: number): Promise<Response> {
    return fetch(`${API_BASE_URL}/api/v1/erp/daily-bank-review/documents/${documentId}/content`);
  }
}

export const dailyBankAuditGateway = new DailyBankAuditGateway();
