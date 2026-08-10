export interface OdooAccount { id: number; code: string; name: string; account_type: string }
export interface OdooPartner { id: number; name: string }
export interface OdooAnalyticAccount { id: number; name: string }
export interface OdooJournal { id: number; code: string; name: string; type: string }
export interface PreviewJournalLine {
  account_id: number;
  account_name: string;
  account_code: string;
  debit: number;
  credit: number;
  name: string;
  partner_name: string;
  partner_id: number | null;
  analytic_account_id: number | null;
  analytic_account_name: string;
}
export interface Worksheet {
  id: string;
  name: string;
  gridData: string[][];
  rowCount: number;
  colCount: number;
}
