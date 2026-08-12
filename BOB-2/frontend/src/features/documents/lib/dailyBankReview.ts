import type { Worksheet } from "@/features/documents/model/types";

export interface DailyBankReviewLine {
  role: "bank" | "counterpart";
  account_id?: number | null;
  account_code?: string | null;
  account_name?: string | null;
  debit: string;
  credit: string;
  name?: string | null;
  partner_name?: string | null;
  analytic_account_name?: string | null;
  bank_rule_name?: string | null;
  confidence?: number | null;
  source_row?: number | null;
  evidence_source?: string | null;
  needs_review?: boolean;
}

export interface DailyBankReviewEntry {
  entry_date: string;
  entry_hash: string;
  journal_id: number;
  journal_name: string;
  journal_code: string;
  bank_account_id: number;
  bank_account_code: string;
  bank_account_name: string;
  company_id?: number | null;
  transaction_count: number;
  line_count: number;
  total_debit: string;
  total_credit: string;
  balanced: boolean;
  unresolved_count: number;
  low_confidence_count: number;
  duplicate_count: number;
  ready_for_review: boolean;
  ready_for_posting: boolean;
  lines: DailyBankReviewLine[];
}

export interface DailyBankReviewDraft {
  documentId: number;
  sourceFilename: string;
  sourceSha256: string;
  journalId: number;
  companyId?: number | null;
  ruleCount: number;
  transactionCount: number;
  unresolvedCount: number;
  lowConfidenceCount: number;
  entries: DailyBankReviewEntry[];
  submitted: boolean;
  reviewIds: number[];
}

function confidenceText(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "";
  return `${Math.round(value * 100)}%`;
}

export function buildDailyBankReviewWorksheets(
  entries: DailyBankReviewEntry[],
  language: string,
  minimumRows: number,
  minimumColumns: number,
): Worksheet[] {
  return entries.map((entry, entryIndex) => {
    const rowCount = Math.max(minimumRows, entry.lines.length + 1);
    const colCount = Math.max(minimumColumns, 10);
    const gridData = Array.from({ length: rowCount }, () => Array(colCount).fill(""));

    gridData[0][0] = language === "ar" ? "رمز الحساب" : "Account Code";
    gridData[0][1] = language === "ar" ? "البيان / الوصف" : "Description";
    gridData[0][2] = language === "ar" ? "مدين" : "Debit";
    gridData[0][3] = language === "ar" ? "دائن" : "Credit";
    gridData[0][4] = language === "ar" ? "الشريك" : "Partner";
    gridData[0][5] = language === "ar" ? "الحساب التحليلي" : "Analytic Account";
    gridData[0][6] = language === "ar" ? "قاعدة البنك" : "Bank Rule";
    gridData[0][7] = language === "ar" ? "الثقة" : "Confidence";
    gridData[0][8] = language === "ar" ? "سطر المصدر" : "Source Row";
    gridData[0][9] = language === "ar" ? "مصدر القرار" : "Evidence Source";

    entry.lines.forEach((line, lineIndex) => {
      const target = lineIndex + 1;
      gridData[target][0] = String(line.account_code || "");
      gridData[target][1] = String(line.name || "");
      gridData[target][2] = line.debit === "0.00" ? "" : String(line.debit || "");
      gridData[target][3] = line.credit === "0.00" ? "" : String(line.credit || "");
      gridData[target][4] = String(line.partner_name || "");
      gridData[target][5] = String(line.analytic_account_name || "");
      gridData[target][6] = line.role === "bank"
        ? (language === "ar" ? "حساب البنك من اليومية" : "Bank journal account")
        : String(line.bank_rule_name || (language === "ar" ? "غير محلول" : "Unresolved"));
      gridData[target][7] = line.role === "counterpart" ? confidenceText(line.confidence) : "";
      gridData[target][8] = line.source_row === null || line.source_row === undefined
        ? ""
        : String(line.source_row);
      gridData[target][9] = String(line.evidence_source || "");
    });

    return {
      id: `daily-bank-${entry.entry_date}-${entryIndex}`,
      name: language === "ar" ? `قيد ${entry.entry_date}` : `Entry ${entry.entry_date}`,
      gridData,
      rowCount,
      colCount,
    };
  });
}
