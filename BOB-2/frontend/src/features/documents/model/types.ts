export interface OdooAccount { id: number; code: string; name: string; account_type: string }
export interface OdooPartner { id: number; name: string }
export interface OdooAnalyticAccount { id: number; name: string }
export interface OdooJournal { id: number; code: string; name: string; type: string }
export interface Worksheet {
  id: string;
  name: string;
  gridData: string[][];
  rowCount: number;
  colCount: number;
}
