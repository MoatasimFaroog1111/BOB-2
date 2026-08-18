import { useCallback } from "react";
import type { Dispatch, SetStateAction } from "react";

import {
  applyGridInlineEdit,
  applyPreviewInlineEdit,
  type SmartAccountingInlineEdit,
} from "@/features/documents/model/smartAccountingInlineEdit";
import type {
  OdooAccount,
  OdooAnalyticAccount,
  OdooPartner,
  PreviewJournalLine,
  Worksheet,
} from "@/features/documents/model/types";

export function useSmartAccountingInlineEdit({
  activeSheetId,
  previewLines,
  setPreviewLines,
  setSheets,
  accounts,
  partners,
  analyticAccounts,
}: {
  activeSheetId: string;
  previewLines: PreviewJournalLine[];
  setPreviewLines: Dispatch<SetStateAction<PreviewJournalLine[]>>;
  setSheets: Dispatch<SetStateAction<Worksheet[]>>;
  accounts: OdooAccount[];
  partners: OdooPartner[];
  analyticAccounts: OdooAnalyticAccount[];
}) {
  return useCallback((edit: SmartAccountingInlineEdit) => {
    const editedPreview = previewLines.length > 0
      ? applyPreviewInlineEdit({
          lines: previewLines,
          edit,
          accounts,
          partners,
          analyticAccounts,
        })
      : null;

    if (editedPreview) setPreviewLines(editedPreview);

    setSheets((current) => current.map((sheet) => {
      if (sheet.id !== activeSheetId) return sheet;
      const baseGrid = editedPreview && !hasAccountingRows(sheet.gridData)
        ? materializePreviewLines(sheet.gridData, editedPreview)
        : sheet.gridData;
      const nextGrid = applyGridInlineEdit({
        gridData: baseGrid,
        edit,
        accounts,
        partners,
        analyticAccounts,
      });
      return {
        ...sheet,
        gridData: nextGrid,
        rowCount: nextGrid.length,
        colCount: nextGrid[0]?.length || sheet.colCount,
      };
    }));
  }, [
    activeSheetId,
    previewLines,
    setPreviewLines,
    setSheets,
    accounts,
    partners,
    analyticAccounts,
  ]);
}

function hasAccountingRows(gridData: string[][]): boolean {
  return gridData.slice(1).some((row) =>
    row.slice(0, 6).some((value) => Boolean(String(value || "").trim())),
  );
}

function materializePreviewLines(
  gridData: string[][],
  lines: PreviewJournalLine[],
): string[][] {
  const next = gridData.map((row) => [...row]);
  lines.forEach((line, index) => {
    const rowIndex = index + 1;
    if (!next[rowIndex]) return;
    next[rowIndex][0] = line.account_code || "";
    next[rowIndex][1] = line.name || "";
    next[rowIndex][2] = line.debit > 0 ? String(line.debit) : "";
    next[rowIndex][3] = line.credit > 0 ? String(line.credit) : "";
    next[rowIndex][4] = line.partner_name || "";
    next[rowIndex][5] = line.analytic_account_name || "";
  });
  return next;
}
