import { requestFormJson, requestJson } from "@/features/settings/shared/http";

export type AccountingIntelligenceStatus = {
  status: string;
  learning_examples: number;
  latest_learning_example_at: string | null;
  mode: string;
  auto_posting: boolean;
};

export type AccountingLearningSyncRequest = {
  date_from?: string | null;
  date_to?: string | null;
  limit: number;
  company_id?: number | null;
  include_attachment_content: boolean;
  attachment_content_limit: number;
};

export type AttachmentContentLearningStats = {
  requested: number;
  extracted: number;
  rejected: number;
  skipped: number;
  failed: number;
};

export type AccountingLearningSyncResult = {
  status: string;
  examples_read: number;
  created: number;
  updated: number;
  unchanged: number;
  vector_indexed: number;
  attachment_content_learning: AttachmentContentLearningStats;
  reference_catalog: Record<string, number>;
  safety: {
    erp_mutation: boolean;
    training_source: string;
    attachment_metadata_used_as_features: boolean;
    attachment_content_enabled: boolean;
    raw_attachment_binaries_read: boolean;
    attachment_content_used_as_features: boolean;
    attachment_content_guard: string;
  };
};

export type AccountingCandidate = {
  id?: number | null;
  label?: string | null;
  code?: string | null;
  name?: string | null;
  type?: string | null;
  account_type?: string | null;
  model_score?: number | null;
  confidence?: number | null;
  selected?: boolean;
  live_reference_resolved?: boolean;
};

export type AccountingDocumentReviewResult = {
  status: string;
  source: {
    filename: string;
    mimetype: string;
    size_bytes: number;
    sha256: string;
    source_reference: string;
  };
  document: {
    document_class: string;
    fields: Record<string, unknown>;
    warnings: string[];
    text_preview: string;
    detected_amount: number | null;
    detected_entry_date: string | null;
    currency: string;
  };
  prediction: {
    model_version?: string;
    bundle_sha256?: string;
    confidence_proxy?: number;
    move_type: AccountingCandidate[];
    journals: AccountingCandidate[];
    debit_accounts: AccountingCandidate[];
    credit_accounts: AccountingCandidate[];
    taxes: AccountingCandidate[];
    analytic_accounts: AccountingCandidate[];
  };
  decision_gate: {
    draft_eligible?: boolean;
    review_required?: boolean;
    auto_post_allowed?: boolean;
    findings?: Array<Record<string, unknown>>;
  };
  partner_candidates: AccountingCandidate[];
  review_defaults: {
    journal_id: number | null;
    debit_account_id: number | null;
    credit_account_id: number | null;
    debit_partner_id: number | null;
    credit_partner_id: number | null;
    debit_analytic_id: number | null;
    credit_analytic_id: number | null;
    counterpart_side: string | null;
  };
};

export type AccountingReviewCatalog = {
  accounts: AccountingCandidate[];
  journals: AccountingCandidate[];
  partners: AccountingCandidate[];
  analytics: AccountingCandidate[];
};

export type ReviewedDraftSelection = {
  file: File;
  companyId: number;
  amount: string;
  entryDate: string;
  journalId: number;
  debitAccountId: number;
  creditAccountId: number;
  debitPartnerId?: number | null;
  creditPartnerId?: number | null;
  debitAnalyticId?: number | null;
  creditAnalyticId?: number | null;
  description?: string;
};

export type ReviewedDraftResult = {
  status: "success" | "partial_success";
  human_review_override: boolean;
  original_decision_gate: Record<string, unknown>;
  odoo_draft: {
    created: boolean;
    idempotent_reuse: boolean;
    move_id: number;
    entry_number: string;
    state: string;
    ref: string;
  };
  attachment: null | {
    created: boolean;
    idempotent_reuse: boolean;
    attachment_id: number;
    move_id: number;
    filename: string;
    mimetype: string;
    sha256: string;
  };
  attachment_error: null | { code: string; message: string };
  audit_logged: boolean;
  safety: {
    state_required: string;
    human_approval_recorded: boolean;
    model_thresholds_changed: boolean;
    auto_posted_to_erp: boolean;
    posting_method_invoked: boolean;
    source_attachment_attached: boolean;
    idempotency_ref: string;
  };
};

export function fetchAccountingIntelligenceStatus() {
  return requestJson<AccountingIntelligenceStatus>("/api/v1/accounting-intelligence/status");
}

export function syncAccountingLearning(payload: AccountingLearningSyncRequest) {
  return requestJson<AccountingLearningSyncResult>("/api/v1/accounting-intelligence/learn/sync", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function analyzeAccountingDocument(file: File, companyId: number, amount?: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("company_id", String(companyId));
  if (amount?.trim()) form.append("amount", amount.trim());
  return requestFormJson<AccountingDocumentReviewResult>(
    "/api/v1/accounting-intelligence/draft/review/analyze",
    form,
  );
}

export async function fetchAccountingReviewCatalog(companyId: number): Promise<AccountingReviewCatalog> {
  const query = `?company_id=${encodeURIComponent(String(companyId))}`;
  const [accounts, journals, partners, analytics] = await Promise.all([
    requestJson<AccountingCandidate[]>(`/api/v1/erp/accounts${query}`),
    requestJson<AccountingCandidate[]>(`/api/v1/erp/journals${query}`),
    requestJson<AccountingCandidate[]>(`/api/v1/erp/partners${query}`),
    requestJson<AccountingCandidate[]>(`/api/v1/erp/analytic-accounts${query}`),
  ]);
  return { accounts, journals, partners, analytics };
}

function appendOptionalId(form: FormData, name: string, value?: number | null) {
  if (value && value > 0) form.append(name, String(value));
}

export function createReviewedAccountingDraft(selection: ReviewedDraftSelection) {
  const form = new FormData();
  form.append("file", selection.file);
  form.append("company_id", String(selection.companyId));
  form.append("amount", selection.amount);
  form.append("entry_date", selection.entryDate);
  form.append("journal_id", String(selection.journalId));
  form.append("debit_account_id", String(selection.debitAccountId));
  form.append("credit_account_id", String(selection.creditAccountId));
  appendOptionalId(form, "debit_partner_id", selection.debitPartnerId);
  appendOptionalId(form, "credit_partner_id", selection.creditPartnerId);
  appendOptionalId(form, "debit_analytic_id", selection.debitAnalyticId);
  appendOptionalId(form, "credit_analytic_id", selection.creditAnalyticId);
  if (selection.description?.trim()) form.append("description", selection.description.trim());
  form.append("reviewer_acknowledged", "true");
  return requestFormJson<ReviewedDraftResult>(
    "/api/v1/accounting-intelligence/draft/review/create",
    form,
  );
}
