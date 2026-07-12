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
  "رابط odoo",
  "entry",
  "date",
  "journal",
  "partner",
  "account",
  "description",
  "debit",
  "credit",
  "odoo",
];

const DATE_HEADERS = ["التاريخ", "date"];
const REF_HEADERS = ["رقم القيد", "رقم المرجع", "reference", "ref", "entry number", "journal entry", "move"];
const JOURNAL_HEADERS = ["الدفتر", "اليومية", "journal"];

const textOf = (el: Element | null | undefined): string =>
  (el?.textContent || "").replace("↗", "").trim();

const normalize = (value: string): string => (value || "").trim().toLowerCase();

const escapeHtml = (value: string): string =>
  String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");

const looksLikeRowNumber = (value: string): boolean => /^\d{1,5}$/.test(String(value || "").trim());
const looksLikeColumnLetter = (value: string): boolean => /^[A-Z]{1,3}$/.test(String(value || "").trim());

const isMostlyColumnLetters = (values: string[]): boolean => {
  const nonEmpty = values.map((v) => v.trim()).filter(Boolean);
  if (nonEmpty.length < 4) return false;
  const letters = nonEmpty.filter(looksLikeColumnLetter).length;
  return letters / nonEmpty.length >= 0.75;
};

const cleanGridValues = (cells: Element[]): string[] => {
  let values = cells.map(textOf);

  if (values.length > 4 && looksLikeRowNumber(values[0])) {
    values = values.slice(1);
  }
  if (values.length > 4 && looksLikeRowNumber(values[values.length - 1])) {
    values = values.slice(0, -1);
  }

  return values.map((value) => value.trim());
};

const rowLooksLikeHeader = (values: string[]): boolean => {
  const normalized = values.map(normalize);
  return normalized.some((value) => HEADER_HINTS.some((hint) => value.includes(hint)));
};

const findHeaderIndex = (rows: HTMLTableRowElement[]): number => {
  for (let i = 0; i < Math.min(rows.length, 30); i++) {
    const values = cleanGridValues(Array.from(rows[i].querySelectorAll("td,th")));
    if (isMostlyColumnLetters(values)) continue;
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
  if (table.closest(".sheet-source-odoo-registration")) return false;
  if (table.closest(".sheet-mirror-odoo-registration")) return false;
  if (table.closest("div.fixed.inset-0")) return false;

  const rows = table.querySelectorAll("tbody tr");
  const cells = table.querySelectorAll("td");
  if (rows.length < 2 || cells.length < 6) return false;

  const firstRowsText = Array.from(rows)
    .slice(0, 25)
    .map((row) => cleanGridValues(Array.from(row.querySelectorAll("td,th"))).join(" "))
    .join(" ")
    .toLowerCase();

  return HEADER_HINTS.some((hint) => firstRowsText.includes(hint));
};

const findSpreadsheetTable = (): HTMLTableElement | null => {
  const gridTables = Array.from(document.querySelectorAll("table"))
    .filter((table) => isLikelySpreadsheetTable(table as HTMLTableElement)) as HTMLTableElement[];

  if (!gridTables.length) return null;
  return gridTables.sort((a, b) => b.querySelectorAll("td").length - a.querySelectorAll("td").length)[0];
};

const snapshotFromTable = (table: HTMLTableElement): SheetSnapshot | null => {
  const rows = Array.from(table.querySelectorAll("tbody tr")) as HTMLTableRowElement[];
  if (!rows.length) return null;

  const headerIndex = findHeaderIndex(rows);
  const headers = cleanGridValues(Array.from(rows[headerIndex]?.querySelectorAll("td,th") || []));
  if (!headers.length) return null;

  const dataRows: string[][] = [];
  for (const row of rows.slice(headerIndex + 1)) {
    const values = cleanGridValues(Array.from(row.querySelectorAll("td,th")));
    const normalizedValues = values.slice(0, headers.length).map((value) => String(value || "").trim());
    if (!normalizedValues.some(Boolean)) continue;
    if (isMostlyColumnLetters(normalizedValues)) continue;
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

const getCurrentSheetSnapshot = (): SheetSnapshot | null => {
  const table = findSpreadsheetTable();
  return table ? snapshotFromTable(table) : null;
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
        text.includes("قيود الحسابات المقترحة") ||
        text.includes("الحساب (أودو)")
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

const findProposalContainers = (modal: HTMLElement): HTMLElement[] => {
  const containers = new Set<HTMLElement>();

  Array.from(modal.querySelectorAll("span,div")).forEach((el) => {
    const text = textOf(el);
    if (text.includes("قيود الحسابات المقترحة") || text.includes("Proposed Journal Items")) {
      const container = el.closest("div.flex.flex-col.gap-2") || el.parentElement;
      if (container instanceof HTMLElement) containers.add(container);
    }
  });

  Array.from(modal.querySelectorAll("table")).forEach((table) => {
    if (table.closest(".sheet-source-odoo-registration")) return;
    const tableText = textOf(table);
    const normalized = normalize(tableText);
    const looksLikeOldProposal =
      tableText.includes("الحساب (أودو)") ||
      normalized.includes("odoo account") ||
      (tableText.includes("مدين") && tableText.includes("دائن") && tableText.includes("الشريك") && tableText.includes("البيان"));

    if (looksLikeOldProposal) {
      const container =
        table.closest("div.flex.flex-col.gap-2") ||
        table.closest("div.border")?.parentElement ||
        table.parentElement;
      if (container instanceof HTMLElement) containers.add(container);
    }
  });

  return Array.from(containers);
};

const getProposalSnapshotFallback = (modal: HTMLElement): SheetSnapshot | null => {
  const oldTable = Array.from(modal.querySelectorAll("table")).find((table) => {
    if (table.closest(".sheet-source-odoo-registration")) return false;
    const text = textOf(table);
    return text.includes("الحساب (أودو)") || text.includes("Odoo Account") || text.includes("قيود الحسابات المقترحة");
  }) as HTMLTableElement | undefined;

  if (!oldTable) return null;
  const headers = cleanGridValues(Array.from(oldTable.querySelectorAll("thead th")));
  const bodyRows = Array.from(oldTable.querySelectorAll("tbody tr")) as HTMLTableRowElement[];
  const rows = bodyRows
    .map((row) => cleanGridValues(Array.from(row.querySelectorAll("td,th"))).slice(0, headers.length))
    .filter((row) => row.some(Boolean));

  if (!headers.length || !rows.length) return null;

  return {
    headers,
    rows,
    capturedAt: Date.now(),
  };
};

const renderWorksheetSourceSection = (snapshot: SheetSnapshot): string => {
  const rows = snapshot.rows.slice(0, 1000);
  const headerHtml = snapshot.headers
    .map((header) => `<th class="px-3 py-2 border-b border-white/10 whitespace-nowrap">${escapeHtml(header)}</th>`)
    .join("");

  const rowsHtml = rows.length
    ? rows
        .map(
          (row) => `
            <tr class="border-b border-white/5 hover:bg-white/5">
              ${snapshot.headers
                .map((_, index) => `<td class="px-3 py-2 whitespace-nowrap text-white/85">${escapeHtml(row[index] || "")}</td>`)
                .join("")}
            </tr>`
        )
        .join("")
    : `<tr><td colspan="${Math.max(snapshot.headers.length, 1)}" class="px-3 py-5 text-center text-red-300">لم يتم التقاط أي صف من الورقة. أغلق هذه الشاشة واضغط تسجيل في Odoo مرة أخرى من الورقة نفسها.</td></tr>`;

  return `
    <div class="sheet-source-odoo-registration flex flex-col gap-2" dir="rtl">
      <div class="flex items-center justify-between gap-3">
        <span class="text-[10.5px] text-emerald-300 font-extrabold">حقول التسجيل من نفس الورقة الحالية:</span>
        <span class="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-3 py-1 text-[10px] font-bold text-emerald-200">${rows.length} سطر</span>
      </div>
      <div class="text-[10px] text-white/45">هذه الشاشة تعرض نفس الأعمدة والقيم التي تم التقاطها من الورقة/جدول التسجيل الحالي. لا توجد مرآة فارغة ولا جدول مقترحات منفصل.</div>
      <div class="border border-emerald-400/25 rounded-xl overflow-auto bg-black/20 text-[11px] max-h-[52vh]">
        <table class="w-full min-w-max text-right border-collapse">
          <thead class="sticky top-0 bg-black/75 text-emerald-200">
            <tr>${headerHtml}</tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
      </div>
    </div>`;
};

const getSnapshotForModal = (modal: HTMLElement): SheetSnapshot | null => {
  const saved = readSavedSnapshot();
  if (saved && saved.rows.length > 0) return saved;

  const live = getCurrentSheetSnapshot();
  if (live && live.rows.length > 0) {
    saveSnapshot(live);
    return live;
  }

  const proposalFallback = getProposalSnapshotFallback(modal);
  if (proposalFallback) return proposalFallback;

  return live || saved;
};

const replaceOldProposalSection = (modal: HTMLElement, snapshot: SheetSnapshot): void => {
  const sectionHtml = renderWorksheetSourceSection(snapshot);

  modal.querySelectorAll(".sheet-mirror-odoo-registration, .sheet-source-odoo-registration").forEach((node) => node.remove());

  const containers = findProposalContainers(modal);
  if (containers.length > 0) {
    containers[0].outerHTML = sectionHtml;
    containers.slice(1).forEach((node) => node.remove());
    return;
  }

  const body = modal.querySelector(".overflow-auto") || modal;
  body.insertAdjacentHTML("afterbegin", sectionHtml);
};

const patchOdooRegistrationModal = (): void => {
  const modal = getOdooRegistrationModal();
  if (!modal) return;

  const snapshot = getSnapshotForModal(modal);
  if (!snapshot) return;

  fillModalHeaderFields(modal, snapshot);
  replaceOldProposalSection(modal, snapshot);
};

const clickedOdooRegisterButton = (target: HTMLElement | null): boolean => {
  const button = target?.closest("button");
  if (!button) return false;
  const text = textOf(button).toLowerCase();

  // Only capture the worksheet when opening the modal. Do not recapture from inside the modal confirm button.
  return (
    (text.includes("تسجيل في odoo") || text.includes("تسجيل في أودو") || text === "register") &&
    !text.includes("تأكيد") &&
    !text.includes("confirm")
  );
};

export default function OdooRegistrationSheetMirror() {
  const pathname = usePathname();

  useEffect(() => {
    if (!pathname?.startsWith("/documents")) return;

    let scheduled = 0;
    const schedulePatch = (delay = 120) => {
      window.clearTimeout(scheduled);
      scheduled = window.setTimeout(patchOdooRegistrationModal, delay);
    };

    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null;
      if (!clickedOdooRegisterButton(target)) return;
      captureCurrentSheetForOdooRegistration();
      [0, 180, 420, 900, 1400].forEach((delay) => window.setTimeout(() => schedulePatch(0), delay));
    };

    document.addEventListener("pointerdown", onPointerDown, true);
    schedulePatch();
    const observer = new MutationObserver(() => schedulePatch());
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });

    return () => {
      window.clearTimeout(scheduled);
      observer.disconnect();
      document.removeEventListener("pointerdown", onPointerDown, true);
    };
  }, [pathname]);

  return null;
}
