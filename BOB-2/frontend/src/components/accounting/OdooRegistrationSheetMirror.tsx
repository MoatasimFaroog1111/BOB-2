"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";
import { API_BASE_URL } from "@/lib/api";

type OdooAccount = { id: number; code: string; name: string; account_type?: string };
type OdooPartner = { id: number; name: string };
type OdooJournal = { id: number; code: string; name: string; type?: string };

type SheetRow = {
  id: string;
  accountOdoo: string;
  cells: string[];
  moveId?: number | null;
};

type SheetWorkspace = {
  headers: string[];
  rows: SheetRow[];
  date: string;
  ref: string;
  journal: string;
};

const ACCOUNT_CODE_REGEX = /(?:^|[^\d.])([0-9][0-9]{4,9})(?![\d.])/g;
const ENTRY_REF_REGEX = /\b[A-Z][A-Z0-9]{1,12}\s*\/\s*\d{4}\s*(?:\/\s*\d{1,2})?\s*\/\s*\d{3,8}\b/i;
const NUMERIC_AMOUNT_REGEX = /^[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?$|^[-+]?\d+(?:\.\d+)?$/;

const normalize = (value: string): string => String(value || "").trim().toLowerCase();
const normalizeEntryRef = (value: string): string =>
  String(value || "").toUpperCase().replace(/\s*\/\s*/g, "/").replace(/\s+/g, "").trim();

const textOf = (el: Element | null | undefined): string => (el?.textContent || "").replace("↗", "").trim();
const valueOfCell = (cell: Element | undefined): string => {
  const link = cell?.querySelector?.("a[href]") as HTMLAnchorElement | null;
  return link?.href || link?.getAttribute?.("href") || textOf(cell);
};

const parseAmount = (value: string): number => {
  const cleaned = String(value || "").replace(/,/g, "").trim();
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? parsed : 0;
};

const looksLikeRowNumber = (value: string): boolean => /^\d{1,5}$/.test(String(value || "").trim());
const looksLikeColumnLetter = (value: string): boolean => /^[A-Z]{1,3}$/.test(String(value || "").trim());
const isMostlyColumnLetters = (values: string[]): boolean => {
  const nonEmpty = values.map((value) => value.trim()).filter(Boolean);
  if (nonEmpty.length < 4) return false;
  const letters = nonEmpty.filter(looksLikeColumnLetter).length;
  return letters / nonEmpty.length >= 0.75;
};

const cleanGridValues = (cells: Element[]): string[] => {
  let values = cells.map(valueOfCell);
  if (values.length > 4 && looksLikeRowNumber(values[0])) values = values.slice(1);
  if (values.length > 4 && looksLikeRowNumber(values[values.length - 1])) values = values.slice(0, -1);
  return values.map((value) => String(value || "").trim());
};

const headerMatches = (header: string, aliases: string[]): boolean => {
  const normalized = normalize(header);
  return aliases.some((alias) => normalized === normalize(alias) || normalized.includes(normalize(alias)));
};

const findColumn = (headers: string[], aliases: string[]): number => headers.findIndex((header) => headerMatches(header, aliases));

const findByAliases = (headers: string[], row: SheetRow, aliases: string[]): string => {
  const idx = findColumn(headers, aliases);
  return idx >= 0 ? String(row.cells[idx] || "").trim() : "";
};

const extractOdooMoveIdFromValue = (value: string): number | null => {
  const raw = String(value || "").replace(/&amp;/g, "&").trim();
  if (!raw) return null;
  let decoded = raw;
  try {
    decoded = decodeURIComponent(raw);
  } catch {
    decoded = raw;
  }
  const idMatch = decoded.match(/(?:^|[#?&])id=(\d+)(?:&|$)/i) || decoded.match(/\bid=(\d+)\b/i);
  const id = idMatch?.[1] ? Number(idMatch[1]) : NaN;
  if (!Number.isFinite(id) || id <= 0) return null;
  if (/model\s*=\s*account\.move/i.test(decoded) || /\/web#|#id=|[?&]id=/i.test(decoded)) return id;
  return null;
};

const extractAccountCodeFromText = (value: string, allowPureNumeric = true): string => {
  const text = String(value || "").replace("↗", "").trim();
  if (!text) return "";
  if (ENTRY_REF_REGEX.test(text)) return "";
  if (!allowPureNumeric && NUMERIC_AMOUNT_REGEX.test(text)) return "";
  for (const match of text.matchAll(ACCOUNT_CODE_REGEX)) {
    const code = match?.[1]?.trim();
    if (code) return code;
  }
  return "";
};

const extractAccountCodeFromRow = (headers: string[], cells: string[]): string => {
  const directColumns = [
    findColumn(headers, ["الحساب (أودو)", "odoo account"]),
    findColumn(headers, ["رمز الحساب", "رقم الحساب", "account code", "account_code", "code"]),
    findColumn(headers, ["اسم الحساب", "الحساب", "account name", "account"]),
  ].filter((index) => index >= 0);

  for (const index of directColumns) {
    const code = extractAccountCodeFromText(cells[index] || "", true);
    if (code) return code;
  }

  for (let index = 0; index < headers.length; index++) {
    const header = normalize(headers[index] || "");
    if (!/حساب|account|code/i.test(header)) continue;
    const code = extractAccountCodeFromText(cells[index] || "", true);
    if (code) return code;
  }

  for (let index = 0; index < cells.length; index++) {
    const header = normalize(headers[index] || "");
    const value = String(cells[index] || "").trim();
    if (!value) continue;
    if (/رقم القيد|entry|move|التاريخ|date|مدين|debit|دائن|credit|رابط|url|reference|ref|مرجع/i.test(header)) continue;
    const code = extractAccountCodeFromText(value, false);
    if (code) return code;
  }

  return "";
};

const normalizeDateForInput = (rawValue: string): string => {
  const value = String(rawValue || "").trim();
  if (!value) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const slash = value.match(/^(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{4})$/);
  if (!slash) return value;
  return `${slash[3]}-${slash[2].padStart(2, "0")}-${slash[1].padStart(2, "0")}`;
};

const findWorksheetTable = (): HTMLTableElement | null => {
  const tables = Array.from(document.querySelectorAll("table")) as HTMLTableElement[];
  const candidates = tables.filter((table) => {
    if (table.closest("div.fixed.inset-0")) return false;
    if (table.closest(".odoo-registration-workspace")) return false;
    const rows = table.querySelectorAll("tbody tr");
    const cells = table.querySelectorAll("td,th");
    if (rows.length < 2 || cells.length < 6) return false;
    const sample = Array.from(rows)
      .slice(0, 20)
      .map((row) => cleanGridValues(Array.from(row.querySelectorAll("td,th"))).join(" "))
      .join(" ")
      .toLowerCase();
    return /رقم القيد|التاريخ|الدفتر|الشريك|رمز الحساب|اسم الحساب|مدين|دائن|entry|date|journal|partner|account|debit|credit/i.test(sample);
  });
  return candidates.sort((a, b) => b.querySelectorAll("td,th").length - a.querySelectorAll("td,th").length)[0] || null;
};

const captureWorkspaceFromSheet = (): SheetWorkspace | null => {
  const table = findWorksheetTable();
  if (!table) return null;

  const domRows = Array.from(table.querySelectorAll("tbody tr")) as HTMLTableRowElement[];
  const cleanedRows = domRows
    .map((row) => cleanGridValues(Array.from(row.querySelectorAll("td,th"))))
    .filter((values) => values.some((value) => String(value || "").trim()));

  const meaningfulRows = cleanedRows.filter((values) => !isMostlyColumnLetters(values));
  if (meaningfulRows.length < 2) return null;

  // Per user requirement: row 1 is always the header row.
  const headers = meaningfulRows[0].map((value, index) => value || `Column ${index + 1}`);
  const rawDataRows = meaningfulRows.slice(1);

  const rows: SheetRow[] = rawDataRows.map((values, rowIndex) => {
    const cells = headers.map((_, index) => String(values[index] || "").trim());
    const accountOdoo = extractAccountCodeFromRow(headers, cells);
    let moveId: number | null = null;
    for (const value of cells) {
      moveId = extractOdooMoveIdFromValue(value);
      if (moveId) break;
    }
    return {
      id: `${Date.now()}-${rowIndex}`,
      accountOdoo,
      cells,
      moveId,
    };
  });

  const firstNonEmpty = (aliases: string[]) => {
    const idx = findColumn(headers, aliases);
    if (idx < 0) return "";
    const row = rows.find((current) => String(current.cells[idx] || "").trim());
    return row ? String(row.cells[idx] || "").trim() : "";
  };

  return {
    headers,
    rows,
    date: normalizeDateForInput(firstNonEmpty(["التاريخ", "date"])),
    ref: firstNonEmpty(["رقم القيد", "رقم المرجع", "reference", "ref", "entry number", "journal entry", "move"]),
    journal: firstNonEmpty(["الدفتر", "اليومية", "journal"]),
  };
};

const isOpenRegistrationButton = (target: HTMLElement | null): boolean => {
  const button = target?.closest("button");
  if (!button) return false;
  const text = textOf(button).toLowerCase();
  if (text.includes("تأكيد") || text.includes("confirm")) return false;
  return text.includes("تسجيل في odoo") || text.includes("تسجيل إلى odoo") || text.includes("register in odoo");
};

export default function OdooRegistrationSheetMirror() {
  const pathname = usePathname();
  const [workspace, setWorkspace] = useState<SheetWorkspace | null>(null);
  const [accounts, setAccounts] = useState<OdooAccount[]>([]);
  const [partners, setPartners] = useState<OdooPartner[]>([]);
  const [journals, setJournals] = useState<OdooJournal[]>([]);
  const [selectedJournalId, setSelectedJournalId] = useState<number | null>(null);
  const [busyAction, setBusyAction] = useState<"register" | "reverse" | "draft" | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const isDocumentsPage = pathname?.startsWith("/documents");

  useEffect(() => {
    if (!isDocumentsPage) return;

    const onClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (!isOpenRegistrationButton(target)) return;
      const captured = captureWorkspaceFromSheet();
      if (!captured || !captured.rows.length) return;

      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      setWorkspace(captured);
      setMessage(null);
    };

    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [isDocumentsPage]);

  useEffect(() => {
    if (!workspace) return;
    const loadOdooData = async () => {
      try {
        const [discoveryRes, partnersRes, journalsRes] = await Promise.all([
          fetch(`${API_BASE_URL}/api/v1/erp/discovery`),
          fetch(`${API_BASE_URL}/api/v1/erp/partners`),
          fetch(`${API_BASE_URL}/api/v1/erp/journals`),
        ]);

        if (discoveryRes.ok) {
          const discovery = await discoveryRes.json();
          setAccounts(discovery.accounts || []);
        }
        if (partnersRes.ok) setPartners(await partnersRes.json());
        if (journalsRes.ok) {
          const loadedJournals = await journalsRes.json();
          setJournals(loadedJournals || []);
          const journalText = normalize(workspace.journal);
          const matched = (loadedJournals || []).find((journal: OdooJournal) =>
            normalize(`${journal.name} ${journal.code}`).includes(journalText) || journalText.includes(normalize(journal.code))
          );
          setSelectedJournalId(matched?.id || loadedJournals?.[0]?.id || null);
        }
      } catch (error) {
        console.error("Failed to load Odoo registration metadata", error);
      }
    };
    loadOdooData();
  }, [workspace]);

  const totalDebit = useMemo(() => {
    if (!workspace) return 0;
    const debitCol = findColumn(workspace.headers, ["مدين", "debit"]);
    return workspace.rows.reduce((sum, row) => sum + parseAmount(debitCol >= 0 ? row.cells[debitCol] : ""), 0);
  }, [workspace]);

  const totalCredit = useMemo(() => {
    if (!workspace) return 0;
    const creditCol = findColumn(workspace.headers, ["دائن", "credit"]);
    return workspace.rows.reduce((sum, row) => sum + parseAmount(creditCol >= 0 ? row.cells[creditCol] : ""), 0);
  }, [workspace]);

  if (!isDocumentsPage || !workspace) return null;

  const updateHeaderField = (field: "date" | "ref" | "journal", value: string) => {
    setWorkspace((previous) => (previous ? { ...previous, [field]: value } : previous));
  };

  const updateAccountOdoo = (rowIndex: number, value: string) => {
    setWorkspace((previous) => {
      if (!previous) return previous;
      return {
        ...previous,
        rows: previous.rows.map((row, index) => (index === rowIndex ? { ...row, accountOdoo: value } : row)),
      };
    });
  };

  const updateCell = (rowIndex: number, cellIndex: number, value: string) => {
    setWorkspace((previous) => {
      if (!previous) return previous;
      return {
        ...previous,
        rows: previous.rows.map((row, index) => {
          if (index !== rowIndex) return row;
          const cells = [...row.cells];
          cells[cellIndex] = value;
          const nextAccount = row.accountOdoo || extractAccountCodeFromRow(previous.headers, cells);
          let moveId = row.moveId || null;
          if (!moveId) {
            for (const cell of cells) {
              moveId = extractOdooMoveIdFromValue(cell);
              if (moveId) break;
            }
          }
          return { ...row, cells, accountOdoo: nextAccount, moveId };
        }),
      };
    });
  };

  const accountByCode = (code: string): OdooAccount | undefined => {
    const clean = String(code || "").trim();
    return accounts.find((account) => account.code === clean || normalize(account.code) === normalize(clean));
  };

  const partnerByName = (name: string): OdooPartner | null => {
    const clean = normalize(name);
    if (!clean) return null;
    return partners.find((partner) => normalize(partner.name) === clean) || partners.find((partner) => normalize(partner.name).includes(clean) || clean.includes(normalize(partner.name))) || null;
  };

  const linePayloads = () => {
    if (!workspace) return [];
    const labelCol = findColumn(workspace.headers, ["البيان", "الوصف", "description", "label", "memo"]);
    const debitCol = findColumn(workspace.headers, ["مدين", "debit"]);
    const creditCol = findColumn(workspace.headers, ["دائن", "credit"]);
    const partnerCol = findColumn(workspace.headers, ["الشريك", "partner", "partner name"]);
    const accountNameCol = findColumn(workspace.headers, ["اسم الحساب", "الحساب", "account name", "account"]);

    return workspace.rows.map((row, index) => {
      const code = String(row.accountOdoo || extractAccountCodeFromRow(workspace.headers, row.cells)).trim();
      const account = accountByCode(code);
      const partnerName = partnerCol >= 0 ? row.cells[partnerCol] || "" : "";
      const partner = partnerByName(partnerName);
      return {
        row_index: index + 1,
        account_code: code,
        account_id: account?.id || 0,
        account_name: account ? `${account.code} ${account.name}` : (accountNameCol >= 0 ? row.cells[accountNameCol] : code),
        partner_name: partner?.name || partnerName,
        partner_id: partner?.id || null,
        label: labelCol >= 0 ? row.cells[labelCol] || "" : "",
        name: labelCol >= 0 ? row.cells[labelCol] || "" : "",
        debit: parseAmount(debitCol >= 0 ? row.cells[debitCol] : ""),
        credit: parseAmount(creditCol >= 0 ? row.cells[creditCol] : ""),
        move_id: row.moveId || undefined,
      };
    });
  };

  const groupedIdentities = () => {
    const groups = new Map<string, { entryNumber: string; moveId?: number | null; rows: typeof workspace.rows }>();
    const entryCol = findColumn(workspace.headers, ["رقم القيد", "entry number", "journal entry", "move"]);
    for (const row of workspace.rows) {
      const entryNumber = normalizeEntryRef(entryCol >= 0 ? row.cells[entryCol] || "" : workspace.ref || "");
      const key = row.moveId ? `move:${row.moveId}` : `entry:${entryNumber}`;
      if (!entryNumber && !row.moveId) continue;
      const current = groups.get(key) || { entryNumber, moveId: row.moveId, rows: [] };
      current.rows.push(row);
      groups.set(key, current);
    }
    return Array.from(groups.values());
  };

  const registerEntries = async () => {
    if (!workspace || busyAction) return;
    const lines = linePayloads();
    const missing = lines.find((line) => !line.account_code || !line.account_id);
    if (missing) {
      setMessage(`لا يمكن التسجيل: السطر رقم ${missing.row_index} لا يحتوي على حساب Odoo معروف. اكتب رقم الحساب الصحيح في خانة الحساب (أودو).`);
      return;
    }
    if (Math.abs(totalDebit - totalCredit) > 0.01) {
      setMessage("لا يمكن التسجيل: إجمالي المدين لا يساوي إجمالي الدائن.");
      return;
    }

    setBusyAction("register");
    setMessage(null);
    try {
      const selectedJournal = journals.find((journal) => journal.id === selectedJournalId);
      const payload = {
        filename: `sheet_registration_${new Date().toISOString().slice(0, 10)}.pdf`,
        document_class: selectedJournal?.type || workspace.journal || "general_journal",
        journal_id: selectedJournalId,
        amount: totalDebit,
        date: normalizeDateForInput(workspace.date) || new Date().toISOString().slice(0, 10),
        partner_name: lines[0]?.partner_name || "",
        partner_id: lines[0]?.partner_id || null,
        ref: workspace.ref || `Sheet Entry ${new Date().toLocaleDateString()}`,
        raw_text: JSON.stringify({ headers: workspace.headers, rows: workspace.rows }),
        lines: lines.map((line) => ({
          account_id: line.account_id,
          account_code: line.account_code,
          account_name: line.account_name,
          debit: line.debit,
          credit: line.credit,
          name: line.name,
          partner_id: line.partner_id,
          analytic_account_id: null,
          analytic_account_name: "",
        })),
      };
      const res = await fetch(`${API_BASE_URL}/api/v1/erp/register-document`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || data.message || (await res.text()));
      setMessage(data.message || "تم تسجيل القيود في Odoo بنجاح.");
    } catch (error: any) {
      setMessage(`فشل تسجيل القيود: ${error.message || error}`);
    } finally {
      setBusyAction(null);
    }
  };

  const resetToDraft = async () => {
    if (!workspace || busyAction) return;
    const groups = groupedIdentities();
    if (!groups.length) {
      setMessage("لا توجد أرقام قيود أو روابط Odoo واضحة لتنفيذ التحويل إلى Draft.");
      return;
    }
    setBusyAction("draft");
    setMessage(null);
    try {
      let ok = 0;
      for (const group of groups) {
        const res = await fetch(`${API_BASE_URL}/api/v1/erp/journal-entry/reset-to-draft`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ entry_number: group.entryNumber || workspace.ref, move_id: group.moveId || undefined }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || data.message || (await res.text()));
        ok += 1;
      }
      setMessage(`تم تنفيذ تحويل إلى Draft لعدد ${ok} قيد/مجموعة.`);
    } catch (error: any) {
      setMessage(`فشل تحويل إلى Draft: ${error.message || error}`);
    } finally {
      setBusyAction(null);
    }
  };

  const reverseEntries = async () => {
    if (!workspace || busyAction) return;
    const groups = groupedIdentities();
    if (!groups.length) {
      setMessage("لا توجد أرقام قيود أو روابط Odoo واضحة لتنفيذ عكس القيود.");
      return;
    }
    if (Math.abs(totalDebit - totalCredit) > 0.01) {
      setMessage("لا يمكن عكس/استبدال القيود لأن الجدول الحالي غير متزن.");
      return;
    }
    setBusyAction("reverse");
    setMessage(null);
    try {
      let ok = 0;
      const allLines = linePayloads();
      for (const group of groups) {
        const entryCol = findColumn(workspace.headers, ["رقم القيد", "entry number", "journal entry", "move"]);
        const groupRowIds = new Set(group.rows.map((row) => row.id));
        const rows = workspace.rows
          .map((row, index) => ({ row, payload: allLines[index] }))
          .filter(({ row }) => groupRowIds.has(row.id))
          .map(({ payload }) => ({
            entry_number: group.entryNumber || workspace.ref,
            account_code: payload.account_code,
            account_name: payload.account_name,
            partner_name: payload.partner_name,
            label: payload.label,
            debit: payload.debit,
            credit: payload.credit,
          }));
        const res = await fetch(`${API_BASE_URL}/api/v1/erp/journal-entry/reverse-and-replace`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            entry_number: group.entryNumber || (entryCol >= 0 ? workspace.rows[0]?.cells[entryCol] : workspace.ref),
            move_id: group.moveId || undefined,
            date: normalizeDateForInput(workspace.date) || undefined,
            ref: workspace.ref || undefined,
            rows,
          }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || data.message || (await res.text()));
        ok += 1;
      }
      setMessage(`تم عكس القيود وإنشاء البدائل لعدد ${ok} قيد/مجموعة.`);
    } catch (error: any) {
      setMessage(`فشل عكس القيود: ${error.message || error}`);
    } finally {
      setBusyAction(null);
    }
  };

  return (
    <div className="odoo-registration-workspace fixed inset-0 z-[95] bg-[#130803] text-white" dir="rtl">
      <div className="flex h-full flex-col overflow-hidden">
        <div className="flex items-center justify-between border-b border-amber-400/20 bg-black/35 px-5 py-4">
          <div>
            <div className="text-[11px] font-bold text-emerald-300">محاسب اول / تسجيل ومعالجة القيود من الورقة</div>
            <h2 className="mt-1 text-xl font-extrabold text-amber-200">شاشة تسجيل القيود من بيانات الورقة الحالية</h2>
            <p className="mt-1 text-xs text-white/50">تم اختيار رؤوس الأعمدة من السطر رقم 1، وكل الخانات أدناه قابلة للتعديل اليدوي قبل تنفيذ الإجراء.</p>
          </div>
          <button onClick={() => setWorkspace(null)} className="rounded-full border border-white/15 px-4 py-2 text-xs font-bold text-white/70 hover:bg-white/10 hover:text-white">
            إغلاق
          </button>
        </div>

        <div className="grid grid-cols-4 gap-3 border-b border-white/10 bg-black/20 p-4 text-xs">
          <label className="flex flex-col gap-1">
            <span className="text-white/45">التاريخ</span>
            <input value={workspace.date} onChange={(e) => updateHeaderField("date", e.target.value)} className="rounded-lg border border-white/10 bg-black/35 px-3 py-2 text-white outline-none focus:border-amber-400/60" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-white/45">رقم المرجع / القيد</span>
            <input value={workspace.ref} onChange={(e) => updateHeaderField("ref", e.target.value)} className="rounded-lg border border-white/10 bg-black/35 px-3 py-2 text-white outline-none focus:border-amber-400/60" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-white/45">اليومية / الدفتر</span>
            <input value={workspace.journal} onChange={(e) => updateHeaderField("journal", e.target.value)} className="rounded-lg border border-white/10 bg-black/35 px-3 py-2 text-white outline-none focus:border-amber-400/60" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-white/45">يومية Odoo للتسجيل</span>
            <select value={selectedJournalId || ""} onChange={(e) => setSelectedJournalId(e.target.value ? Number(e.target.value) : null)} className="rounded-lg border border-white/10 bg-black/35 px-3 py-2 text-white outline-none focus:border-amber-400/60">
              <option value="">اختر اليومية</option>
              {journals.map((journal) => (
                <option key={journal.id} value={journal.id} className="bg-[#1b0d04] text-white">
                  {journal.name} ({journal.code})
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="flex items-center justify-between gap-3 border-b border-white/10 bg-black/10 px-5 py-3 text-xs">
          <div className="flex gap-5">
            <span>إجمالي المدين: <b className="text-emerald-300">{totalDebit.toLocaleString()}</b></span>
            <span>إجمالي الدائن: <b className="text-amber-300">{totalCredit.toLocaleString()}</b></span>
            <span className={Math.abs(totalDebit - totalCredit) <= 0.01 ? "text-emerald-300" : "text-red-300"}>{Math.abs(totalDebit - totalCredit) <= 0.01 ? "قيد متزن" : "غير متزن"}</span>
          </div>
          <div className="rounded-full border border-emerald-400/25 px-3 py-1 text-emerald-200">{workspace.rows.length} سطر من الورقة</div>
        </div>

        {message && (
          <div className={`mx-5 mt-3 rounded-xl border px-4 py-3 text-sm ${message.includes("فشل") || message.includes("لا يمكن") || message.includes("لا توجد") ? "border-red-400/35 bg-red-500/10 text-red-100" : "border-emerald-400/35 bg-emerald-500/10 text-emerald-100"}`}>
            {message}
          </div>
        )}

        <div className="flex-1 overflow-auto p-5">
          <div className="overflow-auto rounded-2xl border border-emerald-400/20 bg-black/20">
            <table className="min-w-full border-collapse text-right text-xs">
              <thead className="sticky top-0 z-10 bg-black/80 text-emerald-200">
                <tr>
                  <th className="border-b border-white/10 px-3 py-2 whitespace-nowrap">الحساب (أودو)</th>
                  {workspace.headers.map((header, index) => (
                    <th key={`${header}-${index}`} className="border-b border-white/10 px-3 py-2 whitespace-nowrap">{header}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {workspace.rows.map((row, rowIndex) => (
                  <tr key={row.id} className="border-b border-white/5 hover:bg-white/5">
                    <td className="px-2 py-1 min-w-[130px]">
                      <input value={row.accountOdoo} onChange={(e) => updateAccountOdoo(rowIndex, e.target.value)} className={`w-full rounded border px-2 py-1 font-mono outline-none ${accountByCode(row.accountOdoo) ? "border-emerald-400/30 bg-emerald-400/5 text-emerald-100" : "border-red-400/40 bg-red-500/10 text-red-100"}`} />
                    </td>
                    {workspace.headers.map((_, cellIndex) => (
                      <td key={`${row.id}-${cellIndex}`} className="px-2 py-1 min-w-[140px]">
                        <input value={row.cells[cellIndex] || ""} onChange={(e) => updateCell(rowIndex, cellIndex, e.target.value)} className="w-full rounded border border-white/10 bg-black/35 px-2 py-1 text-white outline-none focus:border-amber-400/60" />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-white/10 bg-black/40 px-5 py-4">
          <div className="text-[11px] text-white/45">كل إجراء يستخدم القيم المعدلة الظاهرة في هذه الصفحة. الحساب (أودو) يجب أن يكون رقم حساب صحيحًا في Odoo.</div>
          <div className="flex gap-3">
            <button onClick={resetToDraft} disabled={Boolean(busyAction)} className="rounded-xl border border-cyan-400/40 bg-cyan-500/10 px-5 py-2 text-xs font-extrabold text-cyan-200 disabled:opacity-40">{busyAction === "draft" ? "جاري التحويل..." : "تحويل إلى Draft"}</button>
            <button onClick={reverseEntries} disabled={Boolean(busyAction)} className="rounded-xl border border-red-400/40 bg-red-500/10 px-5 py-2 text-xs font-extrabold text-red-100 disabled:opacity-40">{busyAction === "reverse" ? "جاري العكس..." : "عكس القيود"}</button>
            <button onClick={registerEntries} disabled={Boolean(busyAction)} className="rounded-xl border border-emerald-400/40 bg-emerald-500/10 px-5 py-2 text-xs font-extrabold text-emerald-100 disabled:opacity-40">{busyAction === "register" ? "جاري التسجيل..." : "تسجيل القيود"}</button>
          </div>
        </div>
      </div>
    </div>
  );
}
