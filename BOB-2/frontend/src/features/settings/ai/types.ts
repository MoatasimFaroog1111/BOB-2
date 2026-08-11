export type CredentialStatus = {
  configured: boolean;
  storage: string;
  provider: string | null;
  status: string | null;
  version_fingerprint: string | null;
  last_rotated_at: string | null;
};

export type ExternalAIPolicy = {
  id: number;
  external_llm_enabled: boolean;
  approved_provider: string | null;
  approved_model: string | null;
  allowed_purposes: string[];
  allow_redacted_document_text: boolean;
  allow_financial_values: boolean;
  max_redacted_text_chars: number;
  dpa_version: string | null;
  dpa_reference: string | null;
  data_residency_region: string | null;
  provider_retention_mode: string | null;
  accepted_by_user_id: number | null;
  accepted_at: string | null;
  revoked_by_user_id: number | null;
  revoked_at: string | null;
  last_reviewed_at: string | null;
  policy_version: number;
  created_at: string;
  updated_at: string;
};

export type ExternalAISettings = {
  organization_id: number;
  global_enabled: boolean;
  api_key_configured: boolean;
  credential: CredentialStatus;
  effective_enabled: boolean;
  required_dpa_version: string;
  globally_allowed_providers: string[];
  globally_allowed_models: string[];
  provider_catalog: Array<{
    key: string;
    display_name: string;
    models: Array<{ id: string; enabled: boolean }>;
  }>;
  available_purposes: string[];
  available_retention_modes: string[];
  global_max_redacted_text_chars: number;
  policy: ExternalAIPolicy | null;
};

export type ExternalAIConnectionTest = {
  connected: boolean;
  provider: string;
  model: string;
};

export type ExternalAIPolicyInput = {
  external_llm_enabled: boolean;
  approved_provider: string | null;
  approved_model: string | null;
  allowed_purposes: string[];
  allow_redacted_document_text: boolean;
  allow_financial_values: boolean;
  max_redacted_text_chars: number;
  dpa_version: string | null;
  dpa_reference: string | null;
  data_residency_region: string | null;
  provider_retention_mode: string | null;
  accept_dpa: boolean;
};

export type ExternalAIPolicyForm = {
  external_llm_enabled: boolean;
  approved_provider: string;
  approved_model: string;
  allowed_purposes: string[];
  allow_redacted_document_text: boolean;
  allow_financial_values: boolean;
  max_redacted_text_chars: number;
  dpa_version: string;
  dpa_reference: string;
  data_residency_region: string;
  provider_retention_mode: string;
  accept_dpa: boolean;
};
