import { requestJson } from "@/features/settings/shared/http";

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
};

export type AccountingLearningSyncResult = {
  status: string;
  examples_read: number;
  created: number;
  updated: number;
  unchanged: number;
  vector_indexed: number;
  reference_catalog: Record<string, number>;
  safety: {
    erp_mutation: boolean;
    training_source: string;
    raw_attachment_binaries_read: boolean;
    attachment_metadata_used_as_features: boolean;
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
