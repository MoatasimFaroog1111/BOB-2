import type {
  OdooAccount,
  OdooAnalyticAccount,
  OdooJournal,
  OdooPartner,
  PreviewJournalLine,
} from "@/features/documents/model/types";

export type SmartAccountantCandidateLine = {
  accountCode: string;
  description: string;
  debit: number;
  credit: number;
  partnerName: string;
  analyticName: string;
};

export type SmartAccountantVerification = {
  debitTotal: number;
  creditTotal: number;
  balanced: boolean;
  score: number;
  rowsWithKnownAccounts: number;
  accountCodeCount: number;
  rowsWithKnownPartners: number;
  partnerCount: number;
  rowsWithKnownAnalytics: number;
  analyticCount: number;
};

export function buildSmartAccountantCandidateLines(
  gridData: string[][],
): SmartAccountantCandidateLine[] {
  return gridData
    .slice(1)
    .map((row) => ({
      accountCode: String(row?.[0] || "").trim(),
      description: String(row?.[1] || "").trim(),
      debit: parseAmount(row?.[2]),
      credit: parseAmount(row?.[3]),
      partnerName: String(row?.[4] || "").trim(),
      analyticName: String(row?.[5] || "").trim(),
    }))
    .filter((line) =>
      Boolean(
        line.accountCode ||
          line.description ||
          line.debit ||
          line.credit ||
          line.partnerName ||
          line.analyticName,
      ),
    );
}

export function mapPreviewLines(
  lines: PreviewJournalLine[],
): SmartAccountantCandidateLine[] {
  return lines.map((line) => ({
    accountCode: line.account_code,
    description: line.name,
    debit: line.debit,
    credit: line.credit,
    partnerName: line.partner_name,
    analyticName: line.analytic_account_name,
  }));
}

export function verifySmartAccountantContext({
  companySelected,
  selectedJournal,
  lines,
  accounts,
  partners,
  analyticAccounts,
}: {
  companySelected: boolean;
  selectedJournal: OdooJournal | null;
  lines: SmartAccountantCandidateLine[];
  accounts: OdooAccount[];
  partners: OdooPartner[];
  analyticAccounts: OdooAnalyticAccount[];
}): SmartAccountantVerification {
  const debitTotal = lines.reduce((sum, line) => sum + line.debit, 0);
  const creditTotal = lines.reduce((sum, line) => sum + line.credit, 0);
  const balanced = lines.length >= 2 && Math.abs(debitTotal - creditTotal) <= 0.01;

  const accountCodeCount = lines.filter((line) => line.accountCode).length;
  const rowsWithKnownAccounts = lines.filter(
    (line) => line.accountCode && accounts.some((account) => account.code === line.accountCode),
  ).length;

  const partnerNames = lines.map((line) => line.partnerName).filter(Boolean);
  const rowsWithKnownPartners = partnerNames.filter((name) =>
    partners.some(
      (partner) => partner.name.trim().toLocaleLowerCase() === name.trim().toLocaleLowerCase(),
    ),
  ).length;

  const analyticNames = lines.map((line) => line.analyticName).filter(Boolean);
  const rowsWithKnownAnalytics = analyticNames.filter((name) =>
    analyticAccounts.some(
      (analytic) => analytic.name.trim().toLocaleLowerCase() === name.trim().toLocaleLowerCase(),
    ),
  ).length;

  const checks = [
    companySelected,
    Boolean(selectedJournal),
    lines.length >= 2,
    balanced,
    accountCodeCount > 0 && rowsWithKnownAccounts === accountCodeCount,
  ];

  return {
    debitTotal,
    creditTotal,
    balanced,
    score: Math.round((checks.filter(Boolean).length / checks.length) * 100),
    rowsWithKnownAccounts,
    accountCodeCount,
    rowsWithKnownPartners,
    partnerCount: partnerNames.length,
    rowsWithKnownAnalytics,
    analyticCount: analyticNames.length,
  };
}

export function formatAccountingMoney(value: number, currency: string): string {
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${currency}`;
}

function parseAmount(value: string | undefined): number {
  if (!value) return 0;
  const parsed = Number(value.replace(/,/g, "").trim());
  return Number.isFinite(parsed) ? parsed : 0;
}
