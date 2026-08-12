export interface ERPJournal {
  id: number;
  code: string;
  name: string;
  type: string;
}

export interface ERPAccount {
  id: number;
  code: string;
  name: string;
}

export interface BankRuleCondition {
  field: "statement_text" | "amount" | "direction";
  operator: string;
  value?: string;
  min?: string;
  max?: string;
}

export interface BankRuleTarget {
  account_id?: number | null;
  account_code?: string;
  account_name?: string;
  partner_id?: number | null;
  partner_name?: string;
  analytic_account_id?: number | null;
  analytic_account_name?: string;
}

export interface BankRuleVersion {
  id: number;
  version_number: number;
  approval_status: string;
  conditions: BankRuleCondition[];
  target: BankRuleTarget;
  rationale?: string | null;
  change_note?: string | null;
  source_snapshot?: Record<string, any>;
  fingerprint: string;
  approved_at?: string | null;
}

export interface BankRule {
  id: number;
  name: string;
  journal_id: number;
  company_id?: number | null;
  priority: number;
  is_enabled: boolean;
  source_system: string;
  source_external_id?: string | null;
  latest_version?: BankRuleVersion | null;
  approved_version?: BankRuleVersion | null;
  draft_version?: BankRuleVersion | null;
}
