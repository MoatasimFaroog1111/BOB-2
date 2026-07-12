"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";

type SheetSnapshot = {
  headers: string[];
  rows: string[][];
  date?: string;
  ref?: string;
  journal?: string;
  capturedAt?: number;
};

const SNAPSHOT_STORAGE_KEY = "guardianai_odoo_registration_sheet_snapshot";

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
  for (let i = 0; i < Math.min(rows.length, 20); i++) {
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

const isLikelySpreadsheetTable = (table: HTMLTableElement): boolean => {
  if (table.closest(".sheet-mirror-odoo-registration")) return false;
  if (table.closest("div.fixed.inset-0")) return false;

  const text = textOf(table);
  const rows = table.querySelectorAll("tbody tr");
  const cells = table.querySelectorAll("td");
  if (rows.length < 2 || cells.length < 6) return false;

  return (
    text.includes("رمز الحساب") ||
    text.includes("رقم القيد") ||
    text.includes("مدين") ||
    text.includes("دائن") ||
    text.toLowerCase().includes("account") ||
    text.toLowerCase().includes("debit") ||
    text.toLowerCase().includes("credit")
  );
};

const findSpreadsheetTable = (): HTMLTableElement | null => {
  const gridTables = Array.from(document.querySelectorAll("table"))
    .filter((table) => isLikelySpreadsheetTable(table as HTMLTableElement)) as HTMLTableElement[];

  if (!gridTables.length) return null;

  return gridTables.sort((a, b) => b.querySelectorAll("td").length - a.querySelectorAll("td").length)[0];
};

const getCurrentSheetSnapshot = (): SheetSnapshot | null => {
  const table = findSpreadsheetTable();
  if (!table) return null;

  const rows = Array.from(table.querySelectorAll("tbody tr")) as HTMLTableRowElement[];
  if (!rows.length) return null;

  const headerIndex = findHeaderIndex(rows);
  const headerCells = Array.from(rows[headerIndex]?.querySelectorAll("td,th") || []).slice(1);
  const headers = headerCells.map((cell, index) => textOf(cell) || `Column ${index + 1}`);
  if (!headers.length) return null;

  const dataRows: string[][] = [];
  for (const row of rows.slice(headerIndex + 1)) {
    const values = Array.from(row.querySelectorAll("td,th")).slice(1).map(textOf);
    const normalizedValues = values.slice(0, headers.length).map((value) => String(value || "").trim());
    if (!normalizedValues.some(Boolean)) continue;
    if (rowLooksLikeHeader(normalizedValues)) continue;
    dataRows.push(normalizedValues);
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
    capturedAt: Date.now(),
  };
};

const saveSnapshot = (snapshot: SheetSnapshot | null): void => {
  if (!snapshot) return;
  try {
    window.sessionStorage.setItem(SNAPSHOT_STORAGE_KEY, JSON.stringify(snapshot));
  } catch {
    // Ignore storage failures. The live DOM fallback can still be used.
  }
};

const readSavedSnapshot = (): SheetSnapshot | null => {
  try {
    const raw = window.sessionStorage.getItem(SNAPSHOT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as SheetSnapshot;
    if (!parsed.headers?.length) return null;
    // Keep the most recent click snapshot only. It prevents stale values after long navigation.
    if (parsed.capturedAt && Date.now() - parsed.capturedAt > 5 * 60 * 1000) return null;
    return parsed;
  } catch {
    return null;
  }
};

const captureCurrentSheetForOdooRegistration = (): void => {
  const snapshot = getCurrentSheetSnapshot();
  saveSnapshot(snapshot);
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
  const rows = snapshot.rows.slice(0, 500);
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
    : `<tr><td colspan="${Math.max(snapshot.headers.length, 1)}" class="px-3 py-4 text-center text-white/45">لا توجد صفوف مقروءة من الورقة الحالية. حدّد نطاق البيانات في الورقة ثم اضغط تسجيل في Odoo مرة أخرى.</td></tr>`;

  return `
    <div class="sheet-mirror-odoo-registration rounded-xl border border-emerald-400/25 bg-emerald-500/5 p-3 text-right" dir="rtl">
      <div class="mb-2 flex items-center justify-between gap-3">
        <div>
          <div class="text-[11px] font-extrabold text-emerald-300">نفس حقول الورقة الحالية</div>
          <div class="text-[10px] text-white/45">تم التقاط هذه البيانات عند الضغط على زر تسجيل في Odoo، وتعرض نفس أعمدة وقيم الورقة قبل تحويلها إلى قيود Odoo.</div>
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

const getSnapshotForModal = (): SheetSnapshot | null => {
  const saved = readSavedSnapshot();
  if (saved && saved.rows.length > 0) return saved;
  const live = getCurrentSheetSnapshot();
  if (live) saveSnapshot(live);
  return live || saved;
};

const patchOdooRegistrationModal = (): void => {
  const modal = getOdooRegistrationModal();
  if (!modal) return;

  const snapshot = getSnapshotForModal();
  if (!snapshot) return;

  fillModalHeaderFields(modal, snapshot);

  const allMirrors = Array.from(modal.querySelectorAll<HTMLElement>(".sheet-mirror-odoo-registration"));
  const mirrorHtml = renderSheetMirrorTable(snapshot);

  if (allMirrors.length) {
    allMirrors[0].outerHTML = mirrorHtml;
    allMirrors.slice(1).forEach((node) => node.remove());
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

const clickedOdooRegisterButton = (target: HTMLElement | null): boolean => {
  const button = target?.closest("button");
  if (!button) return false;
  const text = textOf(button).toLowerCase();
  return (
    text.includes("تسجيل في odoo") ||
    text.includes("تسجيل القيد في أودو") ||
    text.includes("تأكيد وتسجيل القيد") ||
    text.includes("register")
  );
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

    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null;
      if (!clickedOdooRegisterButton(target)) return;
      captureCurrentSheetForOdooRegistration();
      window.setTimeout(schedulePatch, 0);
      window.setTimeout(schedulePatch, 180);
      window.setTimeout(schedulePatch, 420);
    };

    document.addEventListener("pointerdown", onPointerDown, true);
    schedulePatch();
    const observer = new MutationObserver(schedulePatch);
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });

    return () => {
      window.clearTimeout(scheduled);
      observer.disconnect();
      document.removeEventListener("pointerdown", onPointerDown, true);
    };
  }, [pathname]);

  return null;
}
