import { useState } from "react";

import type { Worksheet } from "@/features/documents/model/types";

export const DEFAULT_WORKSHEET_ROWS = 25;
export const DEFAULT_WORKSHEET_COLUMNS = 10;

export function createEmptyGrid(rows = DEFAULT_WORKSHEET_ROWS, columns = DEFAULT_WORKSHEET_COLUMNS): string[][] {
  return Array.from({ length: rows }, () => Array(columns).fill(""));
}

export function useWorksheets(language: string) {
  const [sheets, setSheets] = useState<Worksheet[]>(() => [{
    id: "sheet-1",
    name: language === "ar" ? "ورقة 1" : "Sheet1",
    gridData: createEmptyGrid(),
    rowCount: DEFAULT_WORKSHEET_ROWS,
    colCount: DEFAULT_WORKSHEET_COLUMNS,
  }]);
  const [activeSheetId, setActiveSheetId] = useState("sheet-1");
  const [renameSheetId, setRenameSheetId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const activeSheet = sheets.find((sheet) => sheet.id === activeSheetId) ?? sheets[0];

  const updateActiveSheet = (update: (sheet: Worksheet) => Worksheet) => {
    setSheets((current) => current.map((sheet) => (
      sheet.id === activeSheetId ? update(sheet) : sheet
    )));
  };

  const addRow = () => updateActiveSheet((sheet) => ({
    ...sheet,
    rowCount: sheet.rowCount + 1,
    gridData: [...sheet.gridData.map((row) => [...row]), Array(sheet.colCount).fill("")],
  }));

  const deleteRow = () => updateActiveSheet((sheet) => sheet.rowCount <= 1 ? sheet : ({
    ...sheet,
    rowCount: sheet.rowCount - 1,
    gridData: sheet.gridData.slice(0, -1),
  }));

  const addColumn = () => updateActiveSheet((sheet) => ({
    ...sheet,
    colCount: sheet.colCount + 1,
    gridData: sheet.gridData.map((row) => [...row, ""]),
  }));

  const deleteColumn = () => updateActiveSheet((sheet) => sheet.colCount <= 1 ? sheet : ({
    ...sheet,
    colCount: sheet.colCount - 1,
    gridData: sheet.gridData.map((row) => row.slice(0, -1)),
  }));

  const clearActiveSheet = () => updateActiveSheet((sheet) => ({
    ...sheet,
    gridData: createEmptyGrid(sheet.rowCount, sheet.colCount),
  }));

  const addSheet = () => {
    const id = `sheet-${Date.now()}`;
    const number = sheets.length + 1;
    setSheets((current) => [...current, {
      id,
      name: language === "ar" ? `ورقة ${number}` : `Sheet${number}`,
      gridData: createEmptyGrid(),
      rowCount: DEFAULT_WORKSHEET_ROWS,
      colCount: DEFAULT_WORKSHEET_COLUMNS,
    }]);
    setActiveSheetId(id);
  };

  const deleteSheet = (id: string) => {
    if (sheets.length <= 1) return;
    const remaining = sheets.filter((sheet) => sheet.id !== id);
    setSheets(remaining);
    if (activeSheetId === id) setActiveSheetId(remaining[remaining.length - 1].id);
  };

  const startRenaming = (id: string, name: string) => {
    setRenameSheetId(id);
    setRenameValue(name);
  };

  const commitRename = () => {
    const name = renameValue.trim();
    if (renameSheetId && name) {
      setSheets((current) => current.map((sheet) => (
        sheet.id === renameSheetId ? { ...sheet, name } : sheet
      )));
    }
    setRenameSheetId(null);
  };

  return {
    sheets,
    setSheets,
    activeSheet,
    activeSheetId,
    setActiveSheetId,
    renameSheetId,
    renameValue,
    setRenameValue,
    addRow,
    deleteRow,
    addColumn,
    deleteColumn,
    clearActiveSheet,
    addSheet,
    deleteSheet,
    startRenaming,
    commitRename,
  };
}
