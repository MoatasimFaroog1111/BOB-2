import React from "react";

import type { SpreadsheetGridInteraction } from "@/features/documents/hooks/useSpreadsheetGridInteraction";

interface SpreadsheetGridProps {
  language: string;
  gridData: string[][];
  rowCount: number;
  colCount: number;
  interaction: SpreadsheetGridInteraction;
}

const columnLetter = (index: number): string => {
  let letter = "";
  for (let value = index; value >= 0; value = Math.floor(value / 26) - 1) {
    letter = String.fromCharCode((value % 26) + 65) + letter;
  }
  return letter;
};

const semanticHeader = (column: number, language: string) => {
  const labels = language === "ar"
    ? ["رمز الحساب", "البيان / الوصف", "مدين", "دائن", "اسم الشريك", "حساب تحليلي"]
    : ["Account Code", "Description", "Debit", "Credit", "Partner", "Analytic Account"];
  return labels[column] ?? "";
};

export function SpreadsheetGrid({ language, gridData, rowCount, colCount, interaction }: SpreadsheetGridProps) {
  const rows = Array.from({ length: rowCount }, (_, index) => index);
  const columns = Array.from({ length: colCount }, (_, index) => index);
  return (
    <div className="flex-1 overflow-auto border border-gray-300 rounded-t-xl bg-white relative" onMouseUp={interaction.handleCellMouseUp}>
      <table onKeyDown={interaction.handleKeyDown} tabIndex={0} className="border-collapse table-fixed w-max min-w-full text-xs font-mono outline-none select-none text-right text-gray-800" dir={language === "ar" ? "rtl" : "ltr"}>
        <thead><tr className="bg-[#f3f3f3] sticky top-0 z-20 border-b border-gray-300">
          <th className="w-10 h-7 border-l border-gray-300 text-center text-[10px] text-gray-400 sticky right-0 z-30 bg-[#f3f3f3]" />
          {columns.map((column) => <th key={column} className="w-32 h-7 border-l border-gray-300 text-center font-bold text-[10.5px] text-gray-600 bg-[#f3f3f3] hover:bg-gray-200 transition-colors">
            {columnLetter(column)}
            {semanticHeader(column, language) && <div className="text-[8.5px] font-normal text-[#107c41] font-semibold">{semanticHeader(column, language)}</div>}
          </th>)}
        </tr></thead>
        <tbody>{rows.map((row) => <tr key={row} className="border-b border-gray-200 h-7 hover:bg-gray-50 bg-white">
          <td className="border-l border-gray-300 text-center text-[10px] font-bold text-gray-500 bg-[#f3f3f3] sticky right-0 z-10">{row + 1}</td>
          {columns.map((column) => {
            const value = gridData[row][column];
            const active = interaction.activeCell?.r === row && interaction.activeCell?.c === column;
            const editing = interaction.editCell?.r === row && interaction.editCell?.c === column;
            const selected = interaction.isCellSelected(row, column);
            const borders = interaction.getSelectionBorders(row, column);
            let cellClass = "px-2 border-l border-gray-200 relative align-middle cursor-cell transition-all select-none ";
            cellClass += editing ? "p-0 z-10 bg-white text-gray-900" : active ? "bg-[#e6f2eb]" : selected ? "bg-[#e2f0d9]" : "bg-white text-gray-800";
            const style: React.CSSProperties = {};
            if (selected && !editing) {
              if (borders.top) style.borderTop = "2px solid #107c41";
              if (borders.bottom) style.borderBottom = "2px solid #107c41";
              if (borders.left) style.borderLeft = "2px solid #107c41";
              if (borders.right) style.borderRight = "2px solid #107c41";
            }
            return <td key={column} className={cellClass} style={style} onMouseDown={(event) => interaction.handleCellMouseDown(row, column, event)} onMouseEnter={() => interaction.handleCellMouseEnter(row, column)} onDoubleClick={() => interaction.startEdit(row, column, value)}>
              {editing ? <input ref={interaction.editInputRef} value={interaction.editValue} onChange={(event) => interaction.setEditValue(event.target.value)} onBlur={interaction.commitEdit} className="w-full h-full bg-white text-gray-900 border-2 border-[#107c41] px-1.5 focus:outline-none text-right font-mono" />
                : <div className={`truncate w-full max-w-[124px] pr-0.5 ${column === 5 && value ? "text-[#107c41] font-semibold" : ""}`}><span className="truncate">{value}</span></div>}
            </td>;
          })}
        </tr>)}</tbody>
      </table>
    </div>
  );
}
