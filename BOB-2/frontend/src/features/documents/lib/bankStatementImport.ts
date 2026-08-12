export interface ParsedBankStatementRow {
  date?: string | null;
  display_date?: string | null;
  description?: string | null;
  debit?: string | number | null;
  credit?: string | number | null;
  amount?: string | number | null;
  balance?: string | number | null;
  suggested_action_label?: string | null;
  detected_category?: string | null;
  ai_suggested_account?: string | null;
}

const BANK_STATEMENT_PARSE_EXTENSIONS = new Set([
  ".xls",
  ".xlsx",
  ".xlsm",
  ".csv",
  ".tsv",
  ".txt",
  ".ofx",
  ".qif",
  ".qfx",
  ".mt940",
  ".sta",
]);

const STRONG_BANK_STATEMENT_MARKERS = [
  "account statement",
  "bank statement",
  "opening balance",
  "open balance",
  "closing balance",
  "credit amount",
  "debit amount",
  "transaction type",
  "value date",
  "كشف حساب",
  "الرصيد الافتتاحي",
  "الرصيد الختامي",
];

function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot >= 0 ? filename.slice(dot).toLowerCase() : "";
}

export function shouldParseAsBankStatement(
  filename: string,
  documentClass: string,
  rawText: string,
): boolean {
  if (!BANK_STATEMENT_PARSE_EXTENSIONS.has(extensionOf(filename))) {
    return false;
  }

  if (documentClass.toLowerCase() === "bank_statement") {
    return true;
  }

  const normalized = rawText.toLowerCase();
  const markerHits = STRONG_BANK_STATEMENT_MARKERS.reduce(
    (count, marker) => count + (normalized.includes(marker) ? 1 : 0),
    0,
  );

  return markerHits >= 2;
}

function numericValue(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(String(value).replace(/,/g, "").trim());
  return Number.isFinite(parsed) ? parsed : null;
}

function moneyCell(value: string | number | null | undefined, *, showZero = false): string {
  const parsed = numericValue(value);
  if (parsed === null) return "";
  if (!showZero && Math.abs(parsed) < 0.0000001) return "";
  return parsed.toFixed(2);
}

export function buildBankStatementGrid(
  rows: ParsedBankStatementRow[],
  language: string,
  minimumRows: number,
  minimumColumns: number,
): { gridData: string[][]; rowCount: number; colCount: number } {
  const rowCount = Math.max(minimumRows, rows.length + 1);
  const colCount = Math.max(minimumColumns, 6);
  const gridData = Array.from({ length: rowCount }, () => Array(colCount).fill(""));

  gridData[0][0] = language === "ar" ? "التاريخ" : "Date";
  gridData[0][1] = language === "ar" ? "البيان / الوصف" : "Description";
  gridData[0][2] = language === "ar" ? "مدين" : "Debit";
  gridData[0][3] = language === "ar" ? "دائن" : "Credit";
  gridData[0][4] = language === "ar" ? "التصنيف المقترح" : "Suggested Classification";
  gridData[0][5] = language === "ar" ? "الرصيد" : "Balance";

  rows.forEach((row, index) => {
    const targetRow = index + 1;
    const amount = numericValue(row.amount);
    const explicitDebit = numericValue(row.debit);
    const explicitCredit = numericValue(row.credit);
    const debit = explicitDebit ?? (amount !== null && amount < 0 ? Math.abs(amount) : 0);
    const credit = explicitCredit ?? (amount !== null && amount > 0 ? amount : 0);

    gridData[targetRow][0] = String(row.display_date || row.date || "");
    gridData[targetRow][1] = String(row.description || "");
    gridData[targetRow][2] = moneyCell(debit);
    gridData[targetRow][3] = moneyCell(credit);
    gridData[targetRow][4] = String(
      row.ai_suggested_account
      || row.suggested_action_label
      || row.detected_category
      || "",
    );
    gridData[targetRow][5] = moneyCell(row.balance, { showZero: true });
  });

  return { gridData, rowCount, colCount };
}
