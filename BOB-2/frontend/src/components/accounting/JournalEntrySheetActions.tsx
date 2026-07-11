"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";
import { API_BASE_URL } from "@/lib/api";

const ENTRY_REF_REGEX = /\b[A-Z][A-Z0-9]{1,12}\s*\/\s*\d{4}\s*(?:\/\s*\d{1,2})?\s*\/\s*\d{3,8}\b/i;

type EntryRow = Record<string, string>;

type SelectedEntry = {
  entryNumber: string;
  headers: string[];
  rows: EntryRow[];
};

const normalizeEntryRef = (value: string): string =>
  (value || "")
    .toUpperCase()
    .replace(/\s*\/\s*/g, "/")
    .replace(/\s+/g, "")
    .trim();

const cellText = (cell: Element | undefined): string => (cell?.textContent || "").trim();

const findHeaderIndex = (rows: HTMLTableRowElement[]): number => {
  for (let i = 0; i < Math.min(rows.length, 12); i++) {
    const cells = Array.from(rows[i].querySelectorAll("td")).slice(1);
    const labels = cells.map((cell) => cellText(cell).toLowerCase());
    const hasEntry = labels.some((label) => ["رقم القيد", "entry number", "journal entry", "move"].includes(label));
    const hasDate = labels.some((label) => ["التاريخ", "date"].includes(label));
    if (hasEntry && hasDate) return i;
  }
  return 0;
};

const findEntryColumn = (headers: string[]): number => {
  const exact = headers.findIndex((header) => {
    const label = header.trim().toLowerCase();
    return ["رقم القيد", "entry number", "journal entry", "move"].includes(label);
  });
  if (exact !== -1) return exact;
  return headers.findIndex((header) => /قيد|entry|move/i.test(header));
};

const extractSelectedEntry = (cell: HTMLElement, entryNumber: string): SelectedEntry => {
  const table = cell.closest("table");
  if (!table) {
    return { entryNumber, headers: [], rows: [] };
  }

  const bodyRows = Array.from(table.querySelectorAll("tbody tr")) as HTMLTableRowElement[];
  const headerIndex = findHeaderIndex(bodyRows);
  const headerCells = Array.from(bodyRows[headerIndex]?.querySelectorAll("td") || []).slice(1);
  const headers = headerCells.map((header, index) => cellText(header) || `Column ${index + 1}`);
  const entryCol = findEntryColumn(headers);

  const rows: EntryRow[] = [];
  for (const row of bodyRows.slice(headerIndex + 1)) {
    const cells = Array.from(row.querySelectorAll("td")).slice(1);
    if (!cells.length) continue;

    const rowValues = cells.map((currentCell) => cellText(currentCell));
    const directValue = entryCol >= 0 ? normalizeEntryRef(rowValues[entryCol] || "") : "";
    const rowHasEntry = directValue === entryNumber || rowValues.some((value) => normalizeEntryRef(value).includes(entryNumber));
    if (!rowHasEntry) continue;

    const mapped: EntryRow = {};
    rowValues.forEach((value, index) => {
      mapped[headers[index] || `Column ${index + 1}`] = value;
    });
    rows.push(mapped);
  }

  return { entryNumber, headers, rows };
};

function decorateJournalEntryCells(): void {
  if (typeof document === "undefined") return;
  const tables = Array.from(document.querySelectorAll("table"));

  for (const table of tables) {
    const rows = Array.from(table.querySelectorAll("tbody tr")) as HTMLTableRowElement[];
    const headerIndex = findHeaderIndex(rows);
    const headerCells = Array.from(rows[headerIndex]?.querySelectorAll("td") || []).slice(1);
    const headers = headerCells.map((header) => cellText(header));
    const entryCol = findEntryColumn(headers);

    for (const row of rows.slice(headerIndex + 1)) {
      const cells = Array.from(row.querySelectorAll("td")).slice(1) as HTMLElement[];
      const candidates = entryCol >= 0 ? [cells[entryCol]] : cells;
      for (const cell of candidates) {
        if (!cell) continue;
        if (cell.querySelector("input, textarea")) continue;
        const match = cellText(cell).match(ENTRY_REF_REGEX);
        if (!match) continue;

        const entryNumber = normalizeEntryRef(match[0]);
        cell.dataset.journalEntryRef = entryNumber;
        cell.classList.add("journal-entry-clickable-cell");
        cell.setAttribute("title", "اضغط لعرض القيد وترحيله إلى Odoo");

        const contentTarget = cell.querySelector("div") || cell;
        if (!contentTarget.querySelector(".journal-entry-click-icon")) {
          const icon = document.createElement("span");
          icon.className = "journal-entry-click-icon";
          icon.textContent = "↗";
          icon.setAttribute("aria-hidden", "true");
          contentTarget.appendChild(icon);
        }
      }
    }
  }
}

export default function JournalEntrySheetActions() {
  const pathname = usePathname();
  const [selectedEntry, setSelectedEntry] = useState<SelectedEntry | null>(null);
  const [posting, setPosting] = useState(false);
  const [postResult, setPostResult] = useState<string | null>(null);
  const [postedEntries, setPostedEntries] = useState<Set<string>>(() => new Set());

  const isDocumentsPage = pathname?.startsWith("/documents");

  useEffect(() => {
    if (!isDocumentsPage) return;

    decorateJournalEntryCells();
    const observer = new MutationObserver(() => decorateJournalEntryCells());
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });

    const onClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (!target) return;
      const cell = target.closest<HTMLElement>("td[data-journal-entry-ref]");
      if (!cell) return;
      if (target.closest("input, textarea")) return;

      event.preventDefault();
      event.stopPropagation();

      const entryNumber = normalizeEntryRef(cell.dataset.journalEntryRef || "");
      if (!entryNumber) return;
      setPostResult(null);
      setSelectedEntry(extractSelectedEntry(cell, entryNumber));
    };

    document.addEventListener("click", onClick, true);
    return () => {
      observer.disconnect();
      document.removeEventListener("click", onClick, true);
    };
  }, [isDocumentsPage]);

  const visibleHeaders = useMemo(() => {
    if (!selectedEntry) return [];
    return selectedEntry.headers.filter((header) => header && selectedEntry.rows.some((row) => String(row[header] || "").trim()));
  }, [selectedEntry]);

  if (!isDocumentsPage || !selectedEntry) return null;

  const handlePostEntry = async () => {
    if (!selectedEntry || posting) return;
    const confirmed = window.confirm(`هل تريد ترحيل القيد ${selectedEntry.entryNumber} إلى Odoo؟`);
    if (!confirmed) return;

    setPosting(true);
    setPostResult(null);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/erp/journal-entry/post`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entry_number: selectedEntry.entryNumber }),
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || data.message || (await res.text()));
      }

      setPostedEntries((prev) => new Set(prev).add(selectedEntry.entryNumber));
      setPostResult(data.message || "تم ترحيل القيد بنجاح في Odoo.");
      decorateJournalEntryCells();
    } catch (err: any) {
      setPostResult(`فشل ترحيل القيد: ${err.message || err}`);
    } finally {
      setPosting(false);
    }
  };

  const isPosted = postedEntries.has(selectedEntry.entryNumber);

  return (
    <>
      <style jsx global>{`
        td.journal-entry-clickable-cell {
          cursor: pointer !important;
          background: linear-gradient(90deg, rgba(16,124,65,0.10), rgba(217,164,65,0.08)) !important;
        }
        td.journal-entry-clickable-cell:hover {
          background: rgba(217,164,65,0.18) !important;
          box-shadow: inset 0 0 0 1px rgba(217,164,65,0.55);
        }
        .journal-entry-click-icon {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-width: 16px;
          height: 16px;
          margin-inline-start: 4px;
          border-radius: 9999px;
          background: rgba(16,124,65,0.15);
          color: #107c41;
          font-size: 10px;
          font-weight: 800;
          vertical-align: middle;
        }
      `}</style>

      <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/65 backdrop-blur-md p-5" dir="rtl">
        <div className="w-full max-w-5xl max-h-[90vh] overflow-hidden rounded-3xl border border-amber-400/25 bg-[#160b05] shadow-2xl flex flex-col">
          <div className="flex items-center justify-between border-b border-white/10 px-5 py-4 bg-black/35">
            <div>
              <div className="text-[11px] text-amber-300/80 font-bold">عرض قيد محاسبي</div>
              <h3 className="text-lg font-extrabold text-white mt-1 flex items-center gap-2">
                <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-amber-400/15 text-amber-300">↗</span>
                {selectedEntry.entryNumber}
              </h3>
              <p className="text-[11px] text-white/45 mt-1">تم تجميع بنود القيد من ورقة القيود الحالية.</p>
            </div>
            <button
              onClick={() => setSelectedEntry(null)}
              className="rounded-full border border-white/15 px-3 py-1.5 text-xs font-bold text-white/70 hover:bg-white/10 hover:text-white"
            >
              إغلاق
            </button>
          </div>

          <div className="flex-1 overflow-auto p-5">
            {postResult && (
              <div className={`mb-4 rounded-xl border px-4 py-3 text-sm ${postResult.includes("فشل") ? "border-red-400/30 bg-red-500/10 text-red-100" : "border-emerald-400/30 bg-emerald-500/10 text-emerald-100"}`}>
                {postResult}
              </div>
            )}

            <div className="overflow-auto rounded-2xl border border-white/10 bg-white/[0.03]">
              <table className="min-w-full border-collapse text-right text-xs text-white/85">
                <thead className="sticky top-0 bg-black/55 text-amber-200">
                  <tr>
                    {visibleHeaders.map((header) => (
                      <th key={header} className="border-b border-white/10 px-3 py-2 font-bold whitespace-nowrap">{header}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {selectedEntry.rows.map((row, rowIndex) => (
                    <tr key={rowIndex} className="border-b border-white/5 hover:bg-white/5">
                      {visibleHeaders.map((header) => (
                        <td key={`${rowIndex}-${header}`} className="px-3 py-2 whitespace-nowrap text-white/75">{row[header]}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="flex items-center justify-between gap-3 border-t border-white/10 bg-black/35 px-5 py-4">
            <p className="text-[11px] text-white/45">
              زر الترحيل يستخدم Odoo action_post على القيد الموجود. إذا كان القيد مرحّلًا مسبقًا فلن يتكرر الترحيل.
            </p>
            <button
              onClick={handlePostEntry}
              disabled={posting || isPosted}
              className="rounded-xl bg-gradient-to-r from-amber-400 to-yellow-600 px-5 py-2.5 text-sm font-extrabold text-black shadow-lg hover:from-amber-300 hover:to-yellow-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {posting ? "جاري الترحيل..." : isPosted ? "تم الترحيل" : "ترحيل القيد إلى Odoo"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
