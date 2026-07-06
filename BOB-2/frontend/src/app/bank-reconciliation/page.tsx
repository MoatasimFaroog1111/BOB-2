"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import JournalEntrySuggestionsEditor from "@/components/JournalEntrySuggestionsEditor";
import { API_BASE_URL } from "@/lib/api";
import { useCompany } from "@/lib/CompanyContext";
import { useLanguage } from "@/lib/LanguageContext";

const SUPPORTED_EXTENSIONS = new Set([
  ".csv", ".tsv", ".txt", ".xlsx", ".xls", ".xlsm",
  ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff",
  ".ofx", ".qfx", ".qif", ".mt940", ".sta",
]);

const MAX_UPLOAD_SIZE_MB = Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_SIZE_MB || "10");
const MAX_UPLOAD_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024;

interface Transaction {
  date: string;
  description: string;
  amount: number;
  row_number: number;
  suggested_action?: string;
  suggested_action_label?: string;
  confidence?: number;
  explanation?: string;
  detected_category?: string;
}

interface MatchedPair {
  statement_txn: Transaction;
  ledger_txn: Transaction;
}

interface SmartMatch {
  statement_txn: Transaction;
  ledger_txn: Transaction;
  confidence: number;
  reason: string;
}

interface BankJournal {
  journal_id: number;
  journal_name: string;
  journal_code: string;
  account_id?: number | null;
  account_name?: string;
  account_code?: string;
  company_id?: number | null;
  company_name?: string;
}

interface ReconciliationResult {
  status: string;
  selected_bank_journal?: BankJournal;
  statement_metadata?: { filename?: string; size?: number; sha256?: string; max_upload_size_mb?: number };
  statement_only: Transaction[];
  ledger_only: Transaction[];
  matched: MatchedPair[];
  smart_matched: SmartMatch[];
  statement_total: number;
  ledger_total: number;
  difference: number;
  statement_count: number;
  ledger_count: number;
  odoo_raw_count: number;
  date_range_used: { from: string | null; to: string | null };
  audit_log_id?: number;
  report_status?: string;
  warning?: string | null;
  footer_note?: string;
  safe_to_post?: boolean;
}

type TabKey = "matched" | "ai_suggested" | "bank_only" | "odoo_only";

function extOf(name: string): string {
  const idx = name.lastIndexOf(".");
  return idx >= 0 ? name.slice(idx).toLowerCase() : "";
}

function formatAmount(val: number): string {
  return Number(val || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function diffColor(diff: number): string {
  const abs = Math.abs(diff);
  if (abs < 0.01) return "text-emerald-400";
  if (abs < 100) return "text-yellow-400";
  return "text-red-400";
}

function confidenceBadge(confidence = 0): string {
  if (confidence >= 0.8) return "bg-emerald-500/20 text-emerald-400 border-emerald-500/30";
  if (confidence >= 0.6) return "bg-yellow-500/20 text-yellow-400 border-yellow-500/30";
  return "bg-red-500/20 text-red-400 border-red-500/30";
}

function pdfEscape(input: string): string {
  return String(input ?? "")
    .replace(/[^\x20-\x7E]/g, "?")
    .replace(/\\/g, "\\\\")
    .replace(/\(/g, "\\(")
    .replace(/\)/g, "\\)");
}

function wrapLine(line: string, width = 105): string[] {
  const plain = line.replace(/\s+/g, " ").trim();
  if (plain.length <= width) return [plain];
  const chunks: string[] = [];
  let rest = plain;
  while (rest.length > width) {
    let cut = rest.lastIndexOf(" ", width);
    if (cut < 40) cut = width;
    chunks.push(rest.slice(0, cut));
    rest = rest.slice(cut).trim();
  }
  if (rest) chunks.push(rest);
  return chunks;
}

function buildPdf(lines: string[]): Blob {
  const wrapped = lines.flatMap((line) => wrapLine(line));
  const perPage = 48;
  const pages: string[][] = [];
  for (let i = 0; i < wrapped.length; i += perPage) pages.push(wrapped.slice(i, i + perPage));
  if (!pages.length) pages.push(["Bank Reconciliation Report"]);

  const objects: string[] = [
    "",
    "<< /Type /Catalog /Pages 2 0 R >>",
    "",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  const pageObjectIds: number[] = [];

  for (const page of pages) {
    const text = ["BT", "/F1 9 Tf", "40 760 Td", "13 TL", ...page.map((line) => `(${pdfEscape(line)}) Tj T*`), "ET"].join("\n");
    objects.push(`<< /Length ${text.length} >>\nstream\n${text}\nendstream`);
    const contentId = objects.length - 1;
    objects.push(`<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 3 0 R >> >> /MediaBox [0 0 612 792] /Contents ${contentId} 0 R >>`);
    pageObjectIds.push(objects.length - 1);
  }

  objects[2] = `<< /Type /Pages /Kids [${pageObjectIds.map((id) => `${id} 0 R`).join(" ")}] /Count ${pageObjectIds.length} >>`;

  let output = "%PDF-1.4\n";
  const offsets = [0];
  for (let i = 1; i < objects.length; i += 1) {
    offsets[i] = output.length;
    output += `${i} 0 obj\n${objects[i]}\nendobj\n`;
  }
  const xref = output.length;
  output += `xref\n0 ${objects.length}\n0000000000 65535 f \n`;
  for (let i = 1; i < objects.length; i += 1) output += `${String(offsets[i]).padStart(10, "0")} 00000 n \n`;
  output += `trailer\n<< /Size ${objects.length} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return new Blob([output], { type: "application/pdf" });
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function truncate(value: string, max = 90): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

export default function BankReconciliationPage() {
  const { t, language } = useLanguage();
  const { selectedCompanyId } = useCompany();
  const inputRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [fileValid, setFileValid] = useState<boolean | null>(null);
  const [fileError, setFileError] = useState("");
  const [isDrag, setIsDrag] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [bankJournals, setBankJournals] = useState<BankJournal[]>([]);
  const [selectedJournalId, setSelectedJournalId] = useState("");
  const [journalsLoading, setJournalsLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saveMessage, setSaveMessage] = useState("");
  const [result, setResult] = useState<ReconciliationResult | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("matched");
  const [showProposedEntries, setShowProposedEntries] = useState(false);

  const msg = useCallback((ar: string, en: string) => (language === "ar" ? ar : en), [language]);

  useEffect(() => {
    let alive = true;
    async function loadJournals() {
      setJournalsLoading(true);
      setError("");
      try {
        const qs = selectedCompanyId ? `?company_id=${selectedCompanyId}` : "";
        const response = await fetch(`${API_BASE_URL}/api/v1/erp/bank-journals${qs}`);
        if (!response.ok) throw new Error(`Error ${response.status}`);
        const data = await response.json();
        const items: BankJournal[] = Array.isArray(data.items) ? data.items : [];
        if (!alive) return;
        setBankJournals(items);
        setSelectedJournalId(items.length === 1 ? String(items[0].journal_id) : "");
      } catch (err) {
        if (!alive) return;
        setBankJournals([]);
        setSelectedJournalId("");
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (alive) setJournalsLoading(false);
      }
    }
    loadJournals();
    return () => { alive = false; };
  }, [selectedCompanyId]);

  const selectedJournal = bankJournals.find((journal) => String(journal.journal_id) === selectedJournalId) || result?.selected_bank_journal;

  const validateFile = useCallback((candidate: File): boolean => {
    const ext = extOf(candidate.name);
    if (!SUPPORTED_EXTENSIONS.has(ext)) {
      setFileError(msg("صيغة الملف غير مدعومة.", "Unsupported file extension."));
      return false;
    }
    if (candidate.size > MAX_UPLOAD_BYTES) {
      setFileError(msg(`حجم الملف يتجاوز الحد الأقصى ${MAX_UPLOAD_SIZE_MB} MB.`, `File exceeds the maximum allowed size of ${MAX_UPLOAD_SIZE_MB} MB.`));
      return false;
    }
    setFileError("");
    return true;
  }, [msg]);

  const handleFile = useCallback((candidate: File) => {
    const valid = validateFile(candidate);
    setFile(candidate);
    setFileValid(valid);
    setError("");
    setSaveMessage("");
    setResult(null);
    setShowProposedEntries(false);
  }, [validateFile]);

  const handleReconcile = async () => {
    if (!file || !fileValid || !selectedJournalId) return;
    setLoading(true);
    setError("");
    setSaveMessage("");
    setShowProposedEntries(false);
    try {
      const form = new FormData();
      form.append("statement", file);
      form.append("bank_journal_id", selectedJournalId);
      if (dateFrom) form.append("date_from", dateFrom);
      if (dateTo) form.append("date_to", dateTo);
      if (selectedCompanyId) form.append("company_id", String(selectedCompanyId));

      const response = await fetch(`${API_BASE_URL}/api/v1/erp/bank-reconciliation`, { method: "POST", body: form });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `Error ${response.status}`);
      }
      const data: ReconciliationResult = await response.json();
      setResult(data);
      setActiveTab("matched");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const exportExcel = async () => {
    if (!result) return;
    try {
      const XLSX = await import("xlsx");
      const wb = XLSX.utils.book_new();
      const journal = result.selected_bank_journal || selectedJournal;
      XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([
        ["Bank Journal", journal ? `${journal.journal_name} (${journal.journal_code})` : "—"],
        [t("bankRecon.dateRangeUsed"), `${result.date_range_used.from || "—"} → ${result.date_range_used.to || "—"}`],
        [t("bankRecon.statementTotal"), result.statement_total],
        [t("bankRecon.ledgerTotal"), result.ledger_total],
        [t("bankRecon.difference"), result.difference],
        [t("bankRecon.statementCount"), result.statement_count],
        [t("bankRecon.ledgerCount"), result.ledger_count],
        [t("bankRecon.matchedCount"), result.matched.length],
        [t("bankRecon.aiSuggestedCount"), result.smart_matched.length],
        [t("bankRecon.bankOnlyCount"), result.statement_only.length],
        [t("bankRecon.odooOnlyCount"), result.ledger_only.length],
        ["Footer", "Reconciliation report generated before any manual posting action."],
      ]), "Summary");
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(result.statement_only), "Bank Only");
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(result.ledger_only), "Odoo Only");
      XLSX.writeFile(wb, "bank-reconciliation.xlsx");
    } catch {
      setError(msg("فشل تصدير Excel.", "Excel export failed."));
    }
  };

  const exportPdf = () => {
    if (!result) return;
    const journal = result.selected_bank_journal || selectedJournal;
    const lines: string[] = [];
    lines.push("Bank Reconciliation AI Report");
    lines.push(`Run timestamp: ${new Date().toISOString()}`);
    lines.push(`Bank journal/account: ${journal ? `${journal.journal_name} (${journal.journal_code}) / ${journal.account_code || ""} ${journal.account_name || ""}` : "Not selected"}`);
    lines.push(`Date range: ${result.date_range_used.from || "-"} to ${result.date_range_used.to || "-"}`);
    lines.push(`Statement total: ${formatAmount(result.statement_total)}`);
    lines.push(`Odoo ledger total: ${formatAmount(result.ledger_total)}`);
    lines.push(`Difference: ${formatAmount(result.difference)}`);
    lines.push(`Statement row count: ${result.statement_count}`);
    lines.push(`Odoo ledger row count: ${result.ledger_count}`);
    lines.push(`Matched count: ${result.matched.length}`);
    lines.push(`AI suggested count: ${result.smart_matched.length}`);
    lines.push(`Bank-only count: ${result.statement_only.length}`);
    lines.push(`Odoo-only count: ${result.ledger_only.length}`);
    lines.push("");
    lines.push("Matched table");
    result.matched.slice(0, 80).forEach((row, idx) => lines.push(`${idx + 1}. ${row.statement_txn.date} | ${formatAmount(row.statement_txn.amount)} | ${truncate(row.statement_txn.description)} | Odoo: ${row.ledger_txn.date} ${truncate(row.ledger_txn.description)}`));
    lines.push("");
    lines.push("AI suggested table with confidence and reason");
    result.smart_matched.slice(0, 80).forEach((row, idx) => lines.push(`${idx + 1}. ${row.statement_txn.date} | ${formatAmount(row.statement_txn.amount)} | confidence ${(row.confidence * 100).toFixed(0)}% | ${truncate(row.reason, 120)}`));
    lines.push("");
    lines.push("Bank-only table");
    result.statement_only.slice(0, 120).forEach((row, idx) => lines.push(`${idx + 1}. ${row.date} | ${formatAmount(row.amount)} | row ${row.row_number} | ${row.suggested_action || "needs_review"} | confidence ${((row.confidence || 0) * 100).toFixed(0)}% | ${truncate(row.description)}`));
    lines.push("");
    lines.push("Odoo-only table");
    result.ledger_only.slice(0, 120).forEach((row, idx) => lines.push(`${idx + 1}. ${row.date} | ${formatAmount(row.amount)} | row ${row.row_number} | ${row.suggested_action || "needs_review"} | confidence ${((row.confidence || 0) * 100).toFixed(0)}% | ${truncate(row.description)}`));
    lines.push("");
    lines.push("Manual proposed journal entries can be previewed separately before posting.");
    downloadBlob(buildPdf(lines), "bank-reconciliation-report.pdf");
  };

  const saveReport = async () => {
    if (!result) return;
    setSaving(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/bank-reconciliation/reports`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          audit_log_id: result.audit_log_id,
          selected_bank_journal: result.selected_bank_journal || selectedJournal,
          statement_metadata: result.statement_metadata,
          date_range_used: result.date_range_used,
          reconciliation_result: result,
        }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `Error ${response.status}`);
      }
      const data = await response.json();
      setResult((current) => current ? { ...current, audit_log_id: data.report_id, report_status: "saved" } : current);
      setSaveMessage(`${data.message} #${data.report_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const tabs: { key: TabKey; label: string; count: number }[] = [
    { key: "matched", label: t("bankRecon.exactMatch"), count: result?.matched.length ?? 0 },
    { key: "ai_suggested", label: t("bankRecon.aiSuggested"), count: result?.smart_matched.length ?? 0 },
    { key: "bank_only", label: t("bankRecon.bankOnly"), count: result?.statement_only.length ?? 0 },
    { key: "odoo_only", label: t("bankRecon.systemOnly"), count: result?.ledger_only.length ?? 0 },
  ];

  const canReconcile = Boolean(file && fileValid && selectedJournalId && !loading);
  const journalForPosting = result?.selected_bank_journal || selectedJournal;
  const bankAccountLabel = journalForPosting ? `${journalForPosting.account_code || ""} ${journalForPosting.account_name || journalForPosting.journal_name || ""}`.trim() : "";

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">{t("bankRecon.pageTitle")}</h1>
        <p className="text-sm text-gray-400 mt-1">{t("bankRecon.pageSubtitle")}</p>
      </div>

      <div className="rounded-2xl border border-white/10 bg-black/30 p-6 space-y-4">
        <h2 className="text-lg font-semibold text-white">{t("bankRecon.uploadStatement")}</h2>
        <div
          onDragOver={(event) => { event.preventDefault(); setIsDrag(true); }}
          onDragLeave={() => setIsDrag(false)}
          onDrop={(event) => { event.preventDefault(); setIsDrag(false); const dropped = event.dataTransfer.files[0]; if (dropped) handleFile(dropped); }}
          onClick={() => inputRef.current?.click()}
          className={`cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition-all ${isDrag ? "border-amber-400 bg-amber-500/10" : "border-white/20 bg-black/20 hover:border-white/30"}`}
        >
          <input ref={inputRef} type="file" className="hidden" accept={Array.from(SUPPORTED_EXTENSIONS).join(",")} onChange={(event) => { const picked = event.target.files?.[0]; if (picked) handleFile(picked); }} />
          <p className="text-white/70">{t("bankRecon.dropStatement")}</p>
          <p className="text-xs text-gray-500 mt-2">{t("bankRecon.supportedFormats")}</p>
          <p className="text-xs text-amber-300/80 mt-1">{msg("الحد الأقصى لحجم الملف", "Maximum file size")}: {MAX_UPLOAD_SIZE_MB} MB</p>
        </div>

        {file && (
          <div className="flex items-center gap-4 rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
            <div className="flex-1 space-y-0.5">
              <p className="text-white font-medium">{file.name}</p>
              <p className="text-gray-500">{fileSize(file.size)} · {extOf(file.name).toUpperCase() || "FILE"}</p>
              {fileError && <p className="text-red-300 text-xs">{fileError}</p>}
            </div>
            <span className={`px-2 py-0.5 rounded-md text-xs font-medium border ${fileValid ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30" : "bg-red-500/20 text-red-400 border-red-500/30"}`}>
              {fileValid ? t("bankRecon.valid") : t("bankRecon.invalid")}
            </span>
          </div>
        )}

        <div className="grid gap-4 lg:grid-cols-4">
          <div className="lg:col-span-2">
            <label className="block text-xs text-gray-400 mb-1">{msg("دفتر البنك / الحساب البنكي", "Bank journal / bank account")}</label>
            <select value={selectedJournalId} onChange={(event) => setSelectedJournalId(event.target.value)} disabled={journalsLoading || bankJournals.length === 0} className="w-full rounded-lg bg-black/40 border border-white/10 text-white text-sm px-3 py-2 outline-none focus:border-amber-400/50 disabled:opacity-50">
              <option value="">{journalsLoading ? msg("جاري تحميل دفاتر البنك...", "Loading bank journals...") : msg("اختر دفتر البنك", "Select bank journal")}</option>
              {bankJournals.map((journal) => (
                <option key={journal.journal_id} value={journal.journal_id}>
                  {journal.journal_name} ({journal.journal_code}) — {journal.account_code || "—"} {journal.company_name ? `— ${journal.company_name}` : ""}
                </option>
              ))}
            </select>
            {bankJournals.length > 1 && !selectedJournalId && <p className="text-xs text-yellow-300 mt-1">{msg("يجب اختيار دفتر البنك قبل بدء التسوية.", "Select a bank journal before reconciliation.")}</p>}
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">{t("bankRecon.dateFrom")}</label>
            <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} className="w-full rounded-lg bg-black/40 border border-white/10 text-white text-sm px-3 py-2 outline-none focus:border-amber-400/50" />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">{t("bankRecon.dateTo")}</label>
            <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} className="w-full rounded-lg bg-black/40 border border-white/10 text-white text-sm px-3 py-2 outline-none focus:border-amber-400/50" />
          </div>
        </div>

        <button disabled={!canReconcile} onClick={handleReconcile} className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-yellow-600 text-black font-semibold text-sm disabled:opacity-40 disabled:cursor-not-allowed transition-all">
          {loading ? t("bankRecon.reconciling") : t("bankRecon.startReconciliation")}
        </button>

        {error && <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">{error}</div>}
      </div>

      {result && (
        <>
          {result.warning && <div className="rounded-xl border border-yellow-500/30 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-200">{result.warning}</div>}
          <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
            {msg("دفتر البنك المحدد", "Selected bank journal")}: {result.selected_bank_journal?.journal_name || selectedJournal?.journal_name || "—"} {result.selected_bank_journal?.journal_code ? `(${result.selected_bank_journal.journal_code})` : ""}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            {[
              { label: t("bankRecon.statementTotal"), value: formatAmount(result.statement_total), color: "text-sky-400" },
              { label: t("bankRecon.ledgerTotal"), value: formatAmount(result.ledger_total), color: "text-sky-400" },
              { label: t("bankRecon.difference"), value: formatAmount(result.difference), color: diffColor(result.difference) },
              { label: t("bankRecon.statementCount"), value: String(result.statement_count), color: "text-white" },
              { label: t("bankRecon.ledgerCount"), value: String(result.ledger_count), color: "text-white" },
              { label: t("bankRecon.matchedCount"), value: String(result.matched.length), color: "text-emerald-400" },
              { label: t("bankRecon.aiSuggestedCount"), value: String(result.smart_matched.length), color: "text-purple-400" },
              { label: t("bankRecon.bankOnlyCount"), value: String(result.statement_only.length), color: result.statement_only.length ? "text-orange-400" : "text-white" },
              { label: t("bankRecon.odooOnlyCount"), value: String(result.ledger_only.length), color: result.ledger_only.length ? "text-orange-400" : "text-white" },
              { label: t("bankRecon.dateRangeUsed"), value: `${result.date_range_used.from || "—"} → ${result.date_range_used.to || "—"}`, color: "text-gray-300" },
            ].map((card) => (
              <div key={card.label} className="rounded-xl border border-white/10 bg-black/30 px-4 py-3">
                <p className="text-[11px] text-gray-500 uppercase tracking-wide">{card.label}</p>
                <p className={`text-lg font-bold mt-1 ${card.color}`}>{card.value}</p>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap gap-3">
            <button onClick={exportExcel} className="px-4 py-2 rounded-lg bg-emerald-600/20 border border-emerald-500/30 text-emerald-400 text-sm font-medium hover:bg-emerald-600/30 transition-colors">{t("bankRecon.exportExcel")}</button>
            <button onClick={exportPdf} className="px-4 py-2 rounded-lg bg-sky-600/20 border border-sky-500/30 text-sky-400 text-sm font-medium hover:bg-sky-600/30 transition-colors">{t("bankRecon.exportPdf")}</button>
            <button disabled={saving || result.report_status === "saved"} onClick={saveReport} className="px-4 py-2 rounded-lg bg-amber-600/20 border border-amber-500/30 text-amber-300 text-sm font-medium hover:bg-amber-600/30 disabled:opacity-40 transition-colors">{saving ? msg("جاري الحفظ...", "Saving...") : msg("حفظ تقرير التسوية", "Save Reconciliation Report")}</button>
            <button disabled={!result.statement_only.length} onClick={() => { setActiveTab("bank_only"); setShowProposedEntries(true); }} className="px-4 py-2 rounded-lg bg-cyan-600/20 border border-cyan-500/30 text-cyan-300 text-sm font-bold hover:bg-cyan-600/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
              🧾 {msg("القيود المقترحة", "Proposed Journal Entries")} ({result.statement_only.length})
            </button>
          </div>
          <p className="text-[11px] text-cyan-200/70">{msg("زر القيود المقترحة يفتح شاشة واسعة لمعاينة قيود العمليات الموجودة في كشف البنك فقط قبل ترحيلها إلى أودو، مع إمكانية ترحيل قيد واحد أو كل القيود.", "Proposed Journal Entries opens a wide preview for bank-statement-only rows before sending them to Odoo, with one-by-one or bulk posting actions.")}</p>
          {saveMessage && <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300">{saveMessage}</div>}

          <div className="flex gap-1 border-b border-white/10 pb-0 overflow-x-auto">
            {tabs.map((tab) => (
              <button key={tab.key} onClick={() => setActiveTab(tab.key)} className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors whitespace-nowrap ${activeTab === tab.key ? "bg-white/10 text-amber-400 border-b-2 border-amber-400" : "text-gray-400 hover:text-white hover:bg-white/5"}`}>
                {tab.label} <span className="text-xs opacity-60">({tab.count})</span>
              </button>
            ))}
          </div>

          <div className="rounded-xl border border-white/10 bg-black/20 overflow-x-auto">
            {activeTab === "matched" && <MatchedTable rows={result.matched} t={t} />}
            {activeTab === "ai_suggested" && <SmartTable rows={result.smart_matched} t={t} />}
            {activeTab === "bank_only" && <ExceptionTable rows={result.statement_only} t={t} empty={t("bankRecon.noDiscrepancies")} />}
            {activeTab === "odoo_only" && <ExceptionTable rows={result.ledger_only} t={t} empty={t("bankRecon.noDiscrepancies")} />}
          </div>
        </>
      )}

      {showProposedEntries && result && (
        <>
          <div className="fixed top-5 left-5 z-[10000]">
            <button onClick={() => setShowProposedEntries(false)} className="rounded-xl border border-rose-500/50 bg-rose-500/20 px-4 py-2 text-xs font-bold text-rose-200 shadow-2xl hover:bg-rose-500/30">
              ✕ {msg("إغلاق القيود المقترحة", "Close proposed entries")}
            </button>
          </div>
          <JournalEntrySuggestionsEditor rows={result.statement_only} isAr={language === "ar"} bankAccountLabel={bankAccountLabel} />
        </>
      )}
    </div>
  );
}

function MatchedTable({ rows, t }: { rows: MatchedPair[]; t: (key: string) => string }) {
  if (!rows.length) return <p className="p-6 text-center text-gray-500">{t("bankRecon.noDiscrepancies")}</p>;
  return (
    <table className="w-full text-sm">
      <thead><tr className="border-b border-white/10 text-gray-400 text-xs uppercase"><th className="px-3 py-2 text-start">{t("bankRecon.date")}</th><th className="px-3 py-2 text-start">{t("bankRecon.description")}</th><th className="px-3 py-2 text-end">{t("bankRecon.amount")}</th><th className="px-3 py-2 text-start">Odoo</th></tr></thead>
      <tbody>{rows.map((row, index) => <tr key={index} className="border-b border-white/5"><td className="px-3 py-2 text-gray-300">{row.statement_txn.date}</td><td className="px-3 py-2 text-white">{row.statement_txn.description}</td><td className="px-3 py-2 text-end text-gray-300">{formatAmount(row.statement_txn.amount)}</td><td className="px-3 py-2 text-gray-300">{row.ledger_txn.date} · {row.ledger_txn.description}</td></tr>)}</tbody>
    </table>
  );
}

function SmartTable({ rows, t }: { rows: SmartMatch[]; t: (key: string) => string }) {
  if (!rows.length) return <p className="p-6 text-center text-gray-500">{t("bankRecon.noDiscrepancies")}</p>;
  return (
    <table className="w-full text-sm">
      <thead><tr className="border-b border-white/10 text-gray-400 text-xs uppercase"><th className="px-3 py-2 text-start">{t("bankRecon.date")}</th><th className="px-3 py-2 text-start">{t("bankRecon.description")}</th><th className="px-3 py-2 text-end">{t("bankRecon.amount")}</th><th className="px-3 py-2 text-center">{t("bankRecon.confidence")}</th><th className="px-3 py-2 text-start">{t("bankRecon.reason")}</th></tr></thead>
      <tbody>{rows.map((row, index) => <tr key={index} className="border-b border-white/5"><td className="px-3 py-2 text-gray-300">{row.statement_txn.date}</td><td className="px-3 py-2 text-white">{row.statement_txn.description}</td><td className="px-3 py-2 text-end text-gray-300">{formatAmount(row.statement_txn.amount)}</td><td className="px-3 py-2 text-center"><span className={`px-2 py-0.5 rounded text-xs border ${confidenceBadge(row.confidence)}`}>{(row.confidence * 100).toFixed(0)}%</span></td><td className="px-3 py-2 text-gray-400 text-xs">{row.reason}</td></tr>)}</tbody>
    </table>
  );
}

function ExceptionTable({ rows, t, empty }: { rows: Transaction[]; t: (key: string) => string; empty: string }) {
  if (!rows.length) return <p className="p-6 text-center text-gray-500">{empty}</p>;
  return (
    <table className="w-full text-sm">
      <thead><tr className="border-b border-white/10 text-gray-400 text-xs uppercase"><th className="px-3 py-2 text-start">{t("bankRecon.date")}</th><th className="px-3 py-2 text-start">{t("bankRecon.description")}</th><th className="px-3 py-2 text-end">{t("bankRecon.amount")}</th><th className="px-3 py-2 text-center">{t("bankRecon.rowNumber")}</th><th className="px-3 py-2 text-start">{t("bankRecon.suggestedAction")}</th><th className="px-3 py-2 text-center">{t("bankRecon.confidence")}</th><th className="px-3 py-2 text-start">{t("bankRecon.reason")}</th></tr></thead>
      <tbody>{rows.map((row, index) => <tr key={index} className="border-b border-white/5"><td className="px-3 py-2 text-gray-300">{row.date}</td><td className="px-3 py-2 text-white">{row.description}<div className="mt-1 text-[11px] text-amber-300/80">{row.detected_category || row.suggested_action || "needs_review"}</div></td><td className="px-3 py-2 text-end text-gray-300">{formatAmount(row.amount)}</td><td className="px-3 py-2 text-center text-gray-500">{row.row_number}</td><td className="px-3 py-2"><span className="px-2 py-0.5 rounded text-xs bg-yellow-500/20 text-yellow-300 border border-yellow-500/30">{row.suggested_action_label || row.suggested_action || t("bankRecon.needsReview")}</span></td><td className="px-3 py-2 text-center"><span className={`px-2 py-0.5 rounded text-xs border ${confidenceBadge(row.confidence || 0)}`}>{((row.confidence || 0) * 100).toFixed(0)}%</span></td><td className="px-3 py-2 text-gray-400 text-xs">{row.explanation || t("bankRecon.needsReview")}</td></tr>)}</tbody>
    </table>
  );
}
