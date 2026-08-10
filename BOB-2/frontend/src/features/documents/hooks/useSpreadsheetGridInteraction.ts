import React, { useEffect, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import type { Worksheet } from "@/features/documents/model/types";
import type { GridSelection } from "@/features/documents/model/prepareJournalEntry";

export interface GridCell { r: number; c: number }
export interface SelectionBorders { top: boolean; bottom: boolean; left: boolean; right: boolean }

interface GridInteractionOptions {
  language: string;
  activeSheetId: string;
  gridData: string[][];
  rowCount: number;
  colCount: number;
  setSheets: Dispatch<SetStateAction<Worksheet[]>>;
}

export function useSpreadsheetGridInteraction({
  language, activeSheetId, gridData, rowCount, colCount, setSheets,
}: GridInteractionOptions) {
  const [activeCell, setActiveCell] = useState<GridCell | null>(null);
  const [selectionRange, setSelectionRange] = useState<GridSelection | null>(null);
  const [editCell, setEditCell] = useState<GridCell | null>(null);
  const [editValue, setEditValue] = useState("");
  const [isSelecting, setIsSelecting] = useState(false);
  const [dragStart, setDragStart] = useState<GridCell | null>(null);
  const editInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editCell && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editCell]);

  useEffect(() => {
    setActiveCell(null);
    setSelectionRange(null);
    setEditCell(null);
  }, [activeSheetId]);

  const selectCell = (r: number, c: number) => {
    setActiveCell({ r, c });
    setSelectionRange({ startR: r, startC: c, endR: r, endC: c });
  };

  const isCellSelected = (r: number, c: number) => {
    if (!selectionRange) return false;
    const minR = Math.min(selectionRange.startR, selectionRange.endR);
    const maxR = Math.max(selectionRange.startR, selectionRange.endR);
    const minC = Math.min(selectionRange.startC, selectionRange.endC);
    const maxC = Math.max(selectionRange.startC, selectionRange.endC);
    return r >= minR && r <= maxR && c >= minC && c <= maxC;
  };

  const getSelectionBorders = (r: number, c: number): SelectionBorders => {
    if (!selectionRange) return { top: false, bottom: false, left: false, right: false };
    const minR = Math.min(selectionRange.startR, selectionRange.endR);
    const maxR = Math.max(selectionRange.startR, selectionRange.endR);
    const minC = Math.min(selectionRange.startC, selectionRange.endC);
    const maxC = Math.max(selectionRange.startC, selectionRange.endC);
    return {
      top: r === minR && isCellSelected(r, c),
      bottom: r === maxR && isCellSelected(r, c),
      left: c === minC && isCellSelected(r, c),
      right: c === maxC && isCellSelected(r, c),
    };
  };

  const commitEdit = () => {
    if (!editCell) return;
    const { r, c } = editCell;
    setSheets((current) => current.map((sheet) => {
      if (sheet.id !== activeSheetId) return sheet;
      const copy = sheet.gridData.map((row) => [...row]);
      copy[r][c] = editValue;
      return { ...sheet, gridData: copy };
    }));
    setEditCell(null);
  };

  const startEdit = (r: number, c: number, value = gridData[r]?.[c] ?? "") => {
    setEditCell({ r, c });
    setEditValue(value);
  };

  const handleCellMouseDown = (r: number, c: number, event: React.MouseEvent) => {
    if (editCell && (editCell.r !== r || editCell.c !== c)) commitEdit();
    if (event.shiftKey && activeCell) {
      setSelectionRange({ startR: activeCell.r, startC: activeCell.c, endR: r, endC: c });
      return;
    }
    selectCell(r, c);
    setIsSelecting(true);
    setDragStart({ r, c });
  };

  const handleCellMouseEnter = (r: number, c: number) => {
    if (isSelecting && dragStart) {
      setSelectionRange({ startR: dragStart.r, startC: dragStart.c, endR: r, endC: c });
    }
  };

  const clearSelectionContents = () => {
    if (!selectionRange) return;
    const minR = Math.min(selectionRange.startR, selectionRange.endR);
    const maxR = Math.max(selectionRange.startR, selectionRange.endR);
    const minC = Math.min(selectionRange.startC, selectionRange.endC);
    const maxC = Math.max(selectionRange.startC, selectionRange.endC);
    setSheets((current) => current.map((sheet) => {
      if (sheet.id !== activeSheetId) return sheet;
      const copy = sheet.gridData.map((row) => [...row]);
      for (let r = minR; r <= maxR; r++) for (let c = minC; c <= maxC; c++) copy[r][c] = "";
      return { ...sheet, gridData: copy };
    }));
  };

  const copySelectionToClipboard = () => {
    if (!selectionRange) return;
    const minR = Math.min(selectionRange.startR, selectionRange.endR);
    const maxR = Math.max(selectionRange.startR, selectionRange.endR);
    const minC = Math.min(selectionRange.startC, selectionRange.endC);
    const maxC = Math.max(selectionRange.startC, selectionRange.endC);
    const rows: string[] = [];
    for (let r = minR; r <= maxR; r++) rows.push(gridData[r].slice(minC, maxC + 1).join("\t"));
    void navigator.clipboard.writeText(rows.join("\n"));
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (!activeCell) return;
    const { r, c } = activeCell;
    if (editCell) {
      if (event.key === "Enter") {
        event.preventDefault(); commitEdit();
        if (r < rowCount - 1) selectCell(r + 1, c);
      } else if (event.key === "Escape") setEditCell(null);
      else if (event.key === "Tab") {
        event.preventDefault(); commitEdit();
        const nextC = c + (event.shiftKey ? -1 : 1);
        if (nextC >= 0 && nextC < colCount) selectCell(r, nextC);
      }
      return;
    }
    if (event.key === "Enter") { event.preventDefault(); startEdit(r, c); return; }
    if (event.key === "Delete" || event.key === "Backspace") { event.preventDefault(); clearSelectionContents(); return; }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "c") { event.preventDefault(); copySelectionToClipboard(); return; }
    if (event.key === "Tab") {
      event.preventDefault();
      const nextC = c + (event.shiftKey ? -1 : 1);
      if (nextC >= 0 && nextC < colCount) selectCell(r, nextC);
      return;
    }
    const directions: Record<string, GridCell> = {
      ArrowUp: { r: r - 1, c }, ArrowDown: { r: r + 1, c },
      ArrowLeft: { r, c: c + (language === "ar" ? 1 : -1) },
      ArrowRight: { r, c: c + (language === "ar" ? -1 : 1) },
    };
    const next = directions[event.key];
    if (next) {
      event.preventDefault();
      if (next.r >= 0 && next.r < rowCount && next.c >= 0 && next.c < colCount) selectCell(next.r, next.c);
    } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      startEdit(r, c, event.key);
    }
  };

  const handlePaste = (event: React.ClipboardEvent) => {
    const target = event.target as HTMLElement;
    if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || !activeCell) return;
    event.preventDefault();
    const rows = event.clipboardData.getData("text/plain").split(/\r?\n/);
    if (!rows.length || (rows.length === 1 && rows[0] === "")) return;
    const parsed = rows.map((row) => row.split("\t"));
    const { r, c } = activeCell;
    const requiredRows = r + parsed.length;
    const requiredColumns = c + Math.max(...parsed.map((row) => row.length));
    setSheets((current) => current.map((sheet) => {
      if (sheet.id !== activeSheetId) return sheet;
      const height = Math.max(sheet.rowCount, requiredRows);
      const width = Math.max(sheet.colCount, requiredColumns);
      const copy = Array.from({ length: height }, (_, rowIndex) =>
        Array.from({ length: width }, (_, columnIndex) => sheet.gridData[rowIndex]?.[columnIndex] || "")
      );
      parsed.forEach((row, rowOffset) => row.forEach((value, columnOffset) => {
        copy[r + rowOffset][c + columnOffset] = value;
      }));
      return { ...sheet, gridData: copy, rowCount: height, colCount: width };
    }));
    setSelectionRange({ startR: r, startC: c, endR: r + parsed.length - 1, endC: c + parsed[0].length - 1 });
  };

  const clearSelection = () => { setActiveCell(null); setSelectionRange(null); setEditCell(null); };

  return {
    activeCell, selectionRange, editCell, editValue, setEditValue, editInputRef,
    isCellSelected, getSelectionBorders, handleCellMouseDown, handleCellMouseEnter,
    handleCellMouseUp: () => setIsSelecting(false), handleKeyDown, handlePaste,
    commitEdit, startEdit, clearSelectionContents, clearSelection,
  };
}

export type SpreadsheetGridInteraction = ReturnType<typeof useSpreadsheetGridInteraction>;
