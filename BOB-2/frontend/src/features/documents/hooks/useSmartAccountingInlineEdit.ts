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
    if (previewLines.length > 0) {
      setPreviewLines((current) => applyPreviewInlineEdit({
        lines: current,
        edit,
        accounts,
        partners,
        analyticAccounts,
      }));
      return;
    }

    setSheets((current) => current.map((sheet) => {
      if (sheet.id !== activeSheetId) return sheet;
      const nextGrid = applyGridInlineEdit({
        gridData: sheet.gridData,
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
    previewLines.length,
    setPreviewLines,
    setSheets,
    accounts,
    partners,
    analyticAccounts,
  ]);
}
