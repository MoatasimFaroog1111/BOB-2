import type {
  OdooAccount,
  OdooAnalyticAccount,
  OdooPartner,
  PreviewJournalLine,
} from "@/features/documents/model/types";

export type SmartAccountingInlineField = "account" | "partner" | "analytic" | "tax";

export type SmartAccountingInlineEdit = {
  field: SmartAccountingInlineField;
  value: string;
};

export function applyPreviewInlineEdit({
  lines,
  edit,
  accounts,
  partners,
  analyticAccounts,
}: {
  lines: PreviewJournalLine[];
  edit: SmartAccountingInlineEdit;
  accounts: OdooAccount[];
  partners: OdooPartner[];
  analyticAccounts: OdooAnalyticAccount[];
}): PreviewJournalLine[] {
  if (lines.length === 0) return lines;

  if (edit.field === "partner") {
    const partner = partners.find((item) => String(item.id) === edit.value) || null;
    return lines.map((line) => ({
      ...line,
      partner_id: partner?.id ?? null,
      partner_name: partner?.name ?? "",
    }));
  }

  if (edit.field === "analytic") {
    const analytic = analyticAccounts.find((item) => String(item.id) === edit.value) || null;
    return lines.map((line) => ({
      ...line,
      analytic_account_id: analytic?.id ?? null,
      analytic_account_name: analytic?.name ?? "",
    }));
  }

  if (edit.field === "account") {
    const account = accounts.find((item) => item.code === edit.value);
    if (!account) return lines;
    const index = findPrimaryLineIndex(lines, accounts);
    if (index < 0) return lines;
    return lines.map((line, lineIndex) => lineIndex === index
      ? { ...line, account_id: account.id, account_code: account.code, account_name: account.name }
      : line);
  }

  const account = accounts.find((item) => item.code === edit.value);
  const taxIndex = findTaxLineIndex(lines, accounts);
  if (!account || taxIndex < 0) return lines;
  return lines.map((line, lineIndex) => lineIndex === taxIndex
    ? { ...line, account_id: account.id, account_code: account.code, account_name: account.name }
    : line);
}

export function applyGridInlineEdit({
  gridData,
  edit,
  accounts,
  partners,
  analyticAccounts,
}: {
  gridData: string[][];
  edit: SmartAccountingInlineEdit;
  accounts: OdooAccount[];
  partners: OdooPartner[];
  analyticAccounts: OdooAnalyticAccount[];
}): string[][] {
  if (gridData.length <= 1) return gridData;
  const next = gridData.map((row) => [...row]);

  if (edit.field === "partner") {
    const partner = partners.find((item) => String(item.id) === edit.value) || null;
    for (let rowIndex = 1; rowIndex < next.length; rowIndex += 1) {
      if (isPopulatedAccountingRow(next[rowIndex])) next[rowIndex][4] = partner?.name || "";
    }
    return next;
  }

  if (edit.field === "analytic") {
    const analytic = analyticAccounts.find((item) => String(item.id) === edit.value) || null;
    for (let rowIndex = 1; rowIndex < next.length; rowIndex += 1) {
      if (isPopulatedAccountingRow(next[rowIndex])) next[rowIndex][5] = analytic?.name || "";
    }
    return next;
  }

  if (edit.field === "account") {
    const rowIndex = findPrimaryGridRowIndex(next, accounts);
    if (rowIndex > 0) next[rowIndex][0] = edit.value;
    return next;
  }

  const taxRowIndex = findTaxGridRowIndex(next, accounts);
  if (taxRowIndex > 0) next[taxRowIndex][0] = edit.value;
  return next;
}

export function listVatAccounts(accounts: OdooAccount[]): OdooAccount[] {
  return accounts.filter((account) => isVatAccountName(account.name));
}

function findPrimaryLineIndex(lines: PreviewJournalLine[], accounts: OdooAccount[]): number {
  const taxIndex = findTaxLineIndex(lines, accounts);
  const accountIndex = lines.findIndex((line, index) => index !== taxIndex && Boolean(line.account_code));
  return accountIndex >= 0 ? accountIndex : 0;
}

function findTaxLineIndex(lines: PreviewJournalLine[], accounts: OdooAccount[]): number {
  return lines.findIndex((line) => {
    const account = accounts.find((item) => item.code === line.account_code);
    return Boolean(account && isVatAccountName(account.name));
  });
}

function findPrimaryGridRowIndex(gridData: string[][], accounts: OdooAccount[]): number {
  const taxRow = findTaxGridRowIndex(gridData, accounts);
  for (let rowIndex = 1; rowIndex < gridData.length; rowIndex += 1) {
    if (rowIndex !== taxRow && isPopulatedAccountingRow(gridData[rowIndex])) return rowIndex;
  }
  return -1;
}

function findTaxGridRowIndex(gridData: string[][], accounts: OdooAccount[]): number {
  for (let rowIndex = 1; rowIndex < gridData.length; rowIndex += 1) {
    const account = accounts.find((item) => item.code === String(gridData[rowIndex]?.[0] || "").trim());
    if (account && isVatAccountName(account.name)) return rowIndex;
  }
  return -1;
}

function isPopulatedAccountingRow(row: string[] | undefined): boolean {
  if (!row) return false;
  return row.slice(0, 6).some((value) => Boolean(String(value || "").trim()));
}

function isVatAccountName(name: string): boolean {
  const normalized = name.trim().toLocaleLowerCase();
  return normalized.includes("vat") || normalized.includes("value added tax") || normalized.includes("ضريبة القيمة المضافة");
}
