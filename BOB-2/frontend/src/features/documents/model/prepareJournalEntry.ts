import type {
  OdooAccount,
  OdooAnalyticAccount,
  OdooJournal,
  OdooPartner,
  PreviewJournalLine,
} from "@/features/documents/model/types";

export interface GridSelection {
  startR: number;
  startC: number;
  endR: number;
  endC: number;
}

interface PrepareJournalEntryInput {
  gridData: string[][];
  rowCount: number;
  colCount: number;
  selectionRange: GridSelection | null;
  language: string;
  analyticAccounts: OdooAnalyticAccount[];
  journals: OdooJournal[];
  selectedJournalId: number | null;
  resolveAccountFromValue: (value: string) => OdooAccount | null;
  resolvePartnerFromValue: (value: string) => OdooPartner | null;
}

export interface PreparedJournalEntry {
  lines: PreviewJournalLine[];
  date: string;
  reference: string;
  journal: string;
}

export function prepareJournalEntry({
  gridData,
  rowCount,
  colCount,
  selectionRange,
  language,
  analyticAccounts,
  journals,
  selectedJournalId,
  resolveAccountFromValue,
  resolvePartnerFromValue,
}: PrepareJournalEntryInput): PreparedJournalEntry | null {
    let codeCol = -1;
    let labelCol = -1;
    let debitCol = -1;
    let creditCol = -1;
    let partnerCol = -1;
    let analyticCol = -1;
    let dateCol = -1;
    let refCol = -1;
    let journalCol = -1;

    let startR = 0;
    let endR = rowCount - 1;
    let startC = 0;
    let endC = colCount - 1;

    // Detect if we should use the active selection range (if covering multiple cells)
    const hasSelection = selectionRange && 
      (selectionRange.endR - selectionRange.startR >= 1) && 
      (selectionRange.endC - selectionRange.startC >= 1);

    if (hasSelection) {
      startR = selectionRange.startR;
      endR = selectionRange.endR;
      startC = selectionRange.startC;
      endC = selectionRange.endC;
    }

    const firstRowInRange = gridData[startR];
    let isHeaderRow = false;
    for (let c = startC; c <= endC; c++) {
      const val = (firstRowInRange[c] || "").toLowerCase().trim();
      if (
        val.includes("حساب") || val.includes("مدين") || val.includes("دائن") || val.includes("شريك") ||
        val.includes("code") || val.includes("debit") || val.includes("credit") || val.includes("partner") ||
        val.includes("date") || val.includes("التاريخ") || val.includes("ref") || val.includes("journal") ||
        val.includes("البيان") || val.includes("وصف") || val.includes("description") || val.includes("name") ||
        val === "الاسم" || val === "الأسم"
      ) {
        isHeaderRow = true;
        break;
      }
    }

    let startRowIndex = startR;
    if (isHeaderRow) {
      startRowIndex = startR + 1;
      for (let c = startC; c <= endC; c++) {
        const val = (firstRowInRange[c] || "").toLowerCase().trim();
        if (val.includes("تحليلي") || val.includes("analytic") || val.includes("مركز تكلفة") || val.includes("cost center")) {
          analyticCol = c;
        } else if ((val.includes("رمز") || val.includes("code") || val.includes("حساب") || val.includes("account")) && !val.includes("تحليلي") && !val.includes("analytic")) {
          codeCol = c;
        } else if (val.includes("بيان") || val.includes("label") || val.includes("وصف") || val.includes("description") || val.includes("name") || val === "الاسم" || val === "الأسم") {
          labelCol = c;
        } else if (val.includes("مدين") || val.includes("debit")) {
          debitCol = c;
        } else if (val.includes("دائن") || val.includes("credit")) {
          creditCol = c;
        } else if (val.includes("شريك") || val.includes("partner") || val.includes("مورد") || val.includes("عميل")) {
          partnerCol = c;
        } else if (val.includes("التاريخ") || val.includes("date")) {
          dateCol = c;
        } else if (val.includes("رقم") || val.includes("ref") || val.includes("move") || val.includes("قيد")) {
          refCol = c;
        } else if (val.includes("دفتر") || val.includes("journal") || val.includes("يومية")) {
          journalCol = c;
        }
      }
    } else {
      // Look at main header row 0
      const mainHeaderRow = gridData[0];
      mainHeaderRow.forEach((val, index) => {
        const norm = val.toLowerCase().trim();
        if (norm.includes("تحليلي") || norm.includes("analytic") || norm.includes("مركز تكلفة") || norm.includes("cost center")) {
          analyticCol = index;
        } else if ((norm.includes("رمز") || norm.includes("code") || norm.includes("حساب") || norm.includes("account")) && !norm.includes("تحليلي") && !norm.includes("analytic")) {
          codeCol = index;
        } else if (norm.includes("بيان") || norm.includes("label") || norm.includes("وصف") || norm.includes("description") || norm.includes("name") || norm === "الاسم" || norm === "الأسم") {
          labelCol = index;
        } else if (norm.includes("مدين") || norm.includes("debit")) {
          debitCol = index;
        } else if (norm.includes("دائن") || norm.includes("credit")) {
          creditCol = index;
        } else if (norm.includes("شريك") || norm.includes("partner") || norm.includes("مورد") || norm.includes("عميل")) {
          partnerCol = index;
        } else if (norm.includes("التاريخ") || norm.includes("date")) {
          dateCol = index;
        } else if (norm.includes("رقم") || norm.includes("ref") || norm.includes("move") || norm.includes("قيد")) {
          refCol = index;
        } else if (norm.includes("دفتر") || norm.includes("journal") || norm.includes("يومية")) {
          journalCol = index;
        }
      });
      const mainHasHeader = mainHeaderRow.some((val) => {
        const norm = val.toLowerCase().trim();
        return norm.includes("حساب") || norm.includes("مدين") || norm.includes("دائن") || norm.includes("شريك") || norm.includes("code") || norm.includes("debit") || norm.includes("credit");
      });
      if (mainHasHeader && startRowIndex === 0) {
        startRowIndex = 1;
      }
    }

    // Fallbacks if columns not identified
    if (codeCol === -1) codeCol = startC;
    if (labelCol === -1) labelCol = startC + 1 <= endC ? startC + 1 : startC;
    if (debitCol === -1) debitCol = startC + 2 <= endC ? startC + 2 : startC;
    if (creditCol === -1) creditCol = startC + 3 <= endC ? startC + 3 : startC;
    if (partnerCol === -1) partnerCol = startC + 4 <= endC ? startC + 4 : startC;
    if (analyticCol === -1 && startC + 5 <= endC) analyticCol = startC + 5;

    const lines: PreviewJournalLine[] = [];
    let extractedDate = "";
    let extractedRef = "";
    let extractedJournal = "";

    for (let r = startRowIndex; r <= endR; r++) {
      const row = gridData[r];
      if (!row) continue;

      const accountCellValue = (row[codeCol] || "").trim();
      const code = accountCellValue;
      const debitVal = parseFloat((row[debitCol] || "").replace(/,/g, "")) || 0;
      const creditVal = parseFloat((row[creditCol] || "").replace(/,/g, "")) || 0;
      const label = (row[labelCol] || "").trim() || (language === "ar" ? "قيد محاسبي تفاعلي" : "Manual Spreadsheet Entry");
      const partnerName = (row[partnerCol] || "").trim();
      const analyticName = analyticCol !== -1 ? (row[analyticCol] || "").trim() : "";

      if (dateCol !== -1 && row[dateCol] && !extractedDate) {
        extractedDate = row[dateCol].trim();
      }
      if (refCol !== -1 && row[refCol] && !extractedRef) {
        extractedRef = row[refCol].trim();
      }
      if (journalCol !== -1 && row[journalCol] && !extractedJournal) {
        extractedJournal = row[journalCol].trim();
      }

      if (!code && debitVal === 0 && creditVal === 0) {
        continue;
      }

      const matchedAcc = resolveAccountFromValue(accountCellValue);

      let resolvedPartnerId: number | null = null;
      let resolvedPartnerName = partnerName;
      if (partnerName) {
        const matchedPartner = resolvePartnerFromValue(partnerName);
        if (matchedPartner) {
          resolvedPartnerId = matchedPartner.id;
          resolvedPartnerName = matchedPartner.name;
        }
      }

      let resolvedAnalyticId: number | null = null;
      let resolvedAnalyticName = analyticName;
      if (analyticName) {
        const matchedAnalytic = analyticAccounts.find((a) =>
          a && a.name && typeof a.name === "string" && a.name.toLowerCase().includes(analyticName.toLowerCase())
        );
        if (matchedAnalytic) {
          resolvedAnalyticId = matchedAnalytic.id;
          resolvedAnalyticName = matchedAnalytic.name;
        }
      }

      lines.push({
        account_id: matchedAcc ? matchedAcc.id : 0,
        account_name: matchedAcc ? `${matchedAcc.code} ${matchedAcc.name}` : (accountCellValue ? `${accountCellValue} (غير معرف)` : "حساب غير محدد"),
        account_code: matchedAcc ? matchedAcc.code : accountCellValue,
        debit: debitVal,
        credit: creditVal,
        name: label,
        partner_name: resolvedPartnerName,
        partner_id: resolvedPartnerId,
        analytic_account_id: resolvedAnalyticId,
        analytic_account_name: resolvedAnalyticName,
      });
    }

    if (lines.length < 2) return null;

    const selectedJournal = journals.find((journal) => journal.id === selectedJournalId);
    return {
      lines,
      date: extractedDate,
      reference: extractedRef,
      journal: extractedJournal || selectedJournal?.code || "",
    };
}

