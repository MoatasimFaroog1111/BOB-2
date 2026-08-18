"use client";

import React from "react";
import type { Worksheet } from "@/features/documents/model/types";

export function WorksheetTabStrip({
  language,
  sheets,
  activeSheetId,
  renameSheetId,
  renameValue,
  renameInputRef,
  onRenameValueChange,
  onActivate,
  onStartRename,
  onCommitRename,
  onDelete,
  onAdd,
}: Readonly<{
  language: string;
  sheets: Worksheet[];
  activeSheetId: string;
  renameSheetId: string | null;
  renameValue: string;
  renameInputRef: React.RefObject<HTMLInputElement | null>;
  onRenameValueChange: (value: string) => void;
  onActivate: (id: string) => void;
  onStartRename: (id: string, name: string) => void;
  onCommitRename: () => void;
  onDelete: (id: string, event: React.MouseEvent) => void;
  onAdd: () => void;
}>) {
  const ar = language === "ar";

  return (
    <div className="flex h-10 shrink-0 items-center gap-1 overflow-x-auto border-t border-white/10 bg-black/25 px-2 py-1">
      {sheets.map((sheet) => {
        const active = sheet.id === activeSheetId;
        const renaming = sheet.id === renameSheetId;
        return (
          <div
            key={sheet.id}
            onClick={() => !renaming && onActivate(sheet.id)}
            onDoubleClick={() => onStartRename(sheet.id, sheet.name)}
            className={`flex h-8 min-w-max cursor-pointer items-center gap-2 rounded-lg border px-3 text-[9.5px] font-bold transition ${
              active
                ? "border-amber-400/25 bg-amber-400/10 text-amber-200"
                : "border-white/10 bg-white/[0.035] text-white/50 hover:bg-white/[0.06] hover:text-white/75"
            }`}
          >
            {renaming ? (
              <input
                ref={renameInputRef}
                value={renameValue}
                onChange={(event) => onRenameValueChange(event.target.value)}
                onBlur={onCommitRename}
                onKeyDown={(event) => event.key === "Enter" && onCommitRename()}
                className="w-24 rounded border border-amber-400/30 bg-black/40 px-1.5 py-0.5 text-[9.5px] text-white outline-none"
              />
            ) : (
              <span>{sheet.name}</span>
            )}
            {sheets.length > 1 ? (
              <button
                type="button"
                onClick={(event) => onDelete(sheet.id, event)}
                className="flex h-4 w-4 items-center justify-center rounded-full text-white/30 hover:bg-red-400/10 hover:text-red-300"
                aria-label={ar ? "حذف ورقة" : "Delete sheet"}
              >
                ×
              </button>
            ) : null}
          </div>
        );
      })}
      <button
        type="button"
        onClick={onAdd}
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] text-white/50 hover:bg-white/[0.08] hover:text-white"
        aria-label={ar ? "إضافة ورقة" : "Add sheet"}
      >
        +
      </button>
    </div>
  );
}
