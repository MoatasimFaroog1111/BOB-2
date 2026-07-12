"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";

type SheetSnapshot = {
  headers: string[];
  rows: string[][];
  date?: string;
  ref?: string;
  journal?: string;
};

const HEADER_HINTS = [
  "رقم القيد",
  "التاريخ",
  "الدفتر",
  "اليومية",
  "الشريك",
  "رمز الحساب",
  "اسم الحساب",
  "البيان",
  "الوصف",
  "مدين",
  "دائن",
  "entry",
  "date",
  "journal",
  "partner",
  "account",
  "description",
  "debit",
  "credit",
];

const DATE_HEADERS = ["التاريخ", "date"];
const REF_HEADERS = ["رقم القيد", "رقم المرجع", "reference", "ref", "entry number", "journal entry", "move"];
const JOURNAL_HEADERS = ["الدفتر", "اليومية", "journal"];

const textOf = (el: Element | null | undefined): string => (el?.textContent || "").replace("↗", "").trim();
const normalize = (value: string): string => (value || "").trim().toLowerCase();

const escapeHtml = (value: string): string =>
  String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");

const rowLooksLikeHeader = (values: string[]): boolean => {
  const normalized = values.map(normalize);
  return normalized.some((value) => HEADER_HINTS.some((hint) => value.includes(hint)));
};

const findHeaderIndex = (rows: HTMLTableRowElement[]): number => {
  for (let i = 0; i < Math.min(rows.length, 15); i++) {
    const values = Array.from(rows[i].querySelectorAll("td,th")).slice(1).map(textOf);
    if (rowLooksLikeHeader(values)) return i;
  }
  return 0;
};

const findColumnIndex = (headers: string[], aliases: string[]): number => {
  return headers.findIndex((header) => {
    const normalized = normalize(header);
    return aliases.some((alias) => normalized === normalize(alias) || normalized.includes(normalize(alias)));
  });
};

const normalizeDateValue = (rawValue: string): string => {
  const value = String(rawValue || "").trim();
  if (!value) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;

  const slash = value.match(/^(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{4})$/);
  if (slash) {
    const day = slash[1].padStart(2, "0");
    const month = slash[2].padStart(2, "0");
    const year = slash[3];
    return `${year}-${month}-${day}`;
  }

  return "";
};

const setInputValue = (input: HTMLInputElement | HTMLSelectElement, value: string): void => {
  if (!value || input.value === value) return;

  const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), "value");
  descriptor?.set?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
};

const getCurrentSheetSnapshot = (): SheetSnapshot | null => {
  const gridTables = Array.from(document.querySelectorAll("table")).filter((table) => {
    if (table.closest(".sheet-mirror-odoo-registration")) return false;
    if (table.closest("div.fixed.inset-0")) return false;
    const rows = table.querySelectorAll("tbody tr");
    const cells = table.querySelectorAll("td");
    return rows.length >= 2 && cells.length >= 6;
  }) as HTMLTableElement[];

  if (!gridTables.length) return null;

  const table = gridTables.sort((a, b) => b.querySelectorAll("td").length - a.querySelectorAll("td").length)[0];
  const rows = Array.from(table.querySelectorAll("tbody tr")) as HTMLTableRowElement[];
  if (!rows.length) return null;

  const headerIndex = findHeaderIndex(rows);
  const headerCells = Array.from(rows[headerIndex]?.querySelectorAll("td,th") || []).slice(1);
  const headers = headerCells.map((cell, index) => textOf(cell) || `Column ${index + 1}`);
  if (!headers.length) return null;

  const dataRows: string[][] = [];
  for (const row of rows.slice(headerIndex + 1)) {
    const values = Array.from(row.querySelectorAll("td,th")).slice(1).map(textOf);
    if (!values.some(Boolean)) continue;
    if (rowLooksLikeHeader(values)) continue;
    dataRows.push(values.slice(0, headers.length));
  }

  const dateCol = findColumnIndex(headers, DATE_HEADERS);
  const refCol = findColumnIndex(headers, REF_HEADERS);
  const journalCol = findColumnIndex(headers, JOURNAL_HEADERS);

  const firstValueFor = (index: number): string => {
    if (index < 0) return "";
    const row = dataRows.find((values) => String(values[index] || "").trim());
    return row ? String(row[index] || "").trim() : "";
  };

  return {
    headers,
    rows: dataRows,
    date: firstValueFor(dateCol),
    ref: firstValueFor(refCol),
    journal: firstValueFor(journalCol),
  };
};

const getOdooRegistrationModal = (): HTMLElement | null => {
  const modals = Array.from(document.querySelectorAll("div.fixed.inset-0")) as HTMLElement[];
  return (
    modals.find((modal) => {
      const text = textOf(modal);
      return (
        text.includes("تسجيل قيد يدوي") ||
        text.includes("تسجيل قيد") ||
        text.includes("Register Odoo Journal Entry") ||
        text.includes("قيود الحسابات المقترحة")
      );
    }) || null
  );
};

const fillModalHeaderFields = (modal: HTMLElement, snapshot: SheetSnapshot): void => {
  const normalizedDate = normalizeDateValue(snapshot.date || "");
  const dateInput = modal.querySelector<HTMLInputElement>('input[type="date"]');
  if (dateInput && normalizedDate) setInputValue(dateInput, normalizedDate);

  const textInputs = Array.from(modal.querySelectorAll<HTMLInputElement>('input[type="text"]'));
  const refInput = textInputs.find((input) => {
    const placeholder = normalize(input.getAttribute("placeholder") || "");
    const labelText = normalize(textOf(input.closest("div")?.querySelector("label")));
    return placeholder.includes("قيد") || placeholder.includes("ref") || labelText.includes("مرجع") || labelText.includes("reference");
  });
  if (refInput && snapshot.ref) setInputValue(refInput, snapshot.ref);

  const journalSelect = modal.querySelector<HTMLSelectElement>("select");
  if (journalSelect && snapshot.journal) {
    const journal = normalize(snapshot.journal);
    const option = Array.from(journalSelect.options).find((opt) => normalize(opt.textContent || "").includes(journal));
    if (option) setInputValue(journalSelect, option.value);
  }
};

const renderSheetMirrorTable = (snapshot: SheetSnapshot): string => {
  const rows = snapshot.rows.slice(0, 250);
  const headerHtml = snapshot.headers
    .map((header) => `<th class="px-3 py-2 border-b border-white/10 whitespace-nowrap">${escapeHtml(header)}</th>`)
    .join("");

  const rowsHtml = rows.length
    ? rows
        .map(
          (row) => `
            <tr class="border-b border-white/5 hover:bg-white/5">
              ${snapshot.headers
                .map((_, index) => `<td class="px-3 py-2 whitespace-nowrap text-white/80">${escapeHtml(row[index] || "")}</td>`)
                .join("")}
            </tr>`
        )
        .join("")
    : `<tr><td colspan="${Math.max(snapshot.headers.length, 1)}" class="px-3 py-4 text-center text-white/45">لا توجد صفوف مقروءة من الورقة الحالية.</td></tr>`;

  return `
    <div class="sheet-mirror-odoo-registration rounded-xl border border-emerald-400/25 bg-emerald-500/5 p-3 text-right" dir="rtl">
      <div class="mb-2 flex items-center justify-between gap-3">
        <div>
          <div class="text-[11px] font-extrabold text-emerald-300">نفس حقول الورقة الحالية</div>
          <div class="text-[10px] text-white/45">تمت تعبئة هذه الشاشة تلقائيًا بنفس أعمدة وقيم الورقة قبل تحويلها لقيود Odoo.</div>
        </div>
        <div class="rounded-full border border-emerald-400/25 px-3 py-1 text-[10px] font-bold text-emerald-200">${rows.length} سطر</div>
      </div>
      <div class="max-h-64 overflow-auto rounded-lg border border-white/10 bg-black/25">
        <table class="min-w-full border-collapse text-xs text-white/85">
          <thead class="sticky top-0 bg-black/70 text-emerald-200">
            <tr>${headerHtml}</tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
      </div>
    </div>`;
};

const patchOdooRegistrationModal = (): void => {
  const modal = getOdooRegistrationModal();
  if (!modal) return;

  const snapshot = getCurrentSheetSnapshot();
  if (!snapshot) return;

  fillModalHeaderFields(modal, snapshot);

  const mirror = modal.querySelector<HTMLElement>(".sheet-mirror-odoo-registration");
  const mirrorHtml = renderSheetMirrorTable(snapshot);

  if (mirror) {
    mirror.outerHTML = mirrorHtml;
    return;
  }

  const proposalLabel = Array.from(modal.querySelectorAll("span,div")).find((el) =>
    textOf(el).includes("قيود الحسابات المقترحة") || textOf(el).includes("Proposed Journal Items")
  );
  const proposalContainer = proposalLabel?.closest("div.flex.flex-col.gap-2") || proposalLabel?.parentElement;

  if (proposalContainer) {
    proposalContainer.insertAdjacentHTML("beforebegin", mirrorHtml);
  } else {
    const body = modal.querySelector(".overflow-auto") || modal;
    body.insertAdjacentHTML("afterbegin", mirrorHtml);
  }
};

export default function OdooRegistrationSheetMirror() {
  const pathname = usePathname();

  useEffect(() => {
    if (!pathname?.startsWith("/documents")) return;

    let scheduled = 0;
    const schedulePatch = () => {
      window.clearTimeout(scheduled);
      scheduled = window.setTimeout(patchOdooRegistrationModal, 120);
    };

    schedulePatch();
    const observer = new MutationObserver(schedulePatch);
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });

    return () => {
      window.clearTimeout(scheduled);
      observer.disconnect();
    };
  }, [pathname]);

  return null;
}
