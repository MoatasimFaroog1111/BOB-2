"use client";

import React, { useState, useRef, useCallback } from "react";
import { useLanguage } from "@/lib/LanguageContext";
import { useCompany } from "@/lib/CompanyContext";
import { API_BASE_URL } from "@/lib/api";

const SUPPORTED_EXTENSIONS = new Set([
  ".csv",".tsv",".txt",".xlsx",".xls",".xlsm",
  ".pdf",".png",".jpg",".jpeg",".webp",".bmp",".tif",".tiff",
  ".ofx",".qfx",".qif",".mt940",".sta",
]);

interface Transaction {
  date: string;
  description: string;
  amount: number;
  row_number: number;
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

interface ReconciliationResult {
  status: string;
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
}

type TabKey = "matched" | "ai_suggested" | "bank_only" | "odoo_only";

function formatAmount(val: number): string {
  return val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function diffColor(diff: number): string {
  const abs = Math.abs(diff);
  if (abs < 0.01) return "text-emerald-400";
  if (abs < 100) return "text-yellow-400";
  return "text-red-400";
}

function confidenceBadge(c: number): string {
  if (c >= 0.8) return "bg-emerald-500/20 text-emerald-400 border-emerald-500/30";
  if (c >= 0.6) return "bg-yellow-500/20 text-yellow-400 border-yellow-500/30";
  return "bg-red-500/20 text-red-400 border-red-500/30";
}

function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function BankReconciliationPage() {
  const { t, language } = useLanguage();
  const { selectedCompanyId } = useCompany();

  const [file, setFile] = useState<File | null>(null);
  const [fileValid, setFileValid] = useState<boolean | null>(null);
  const [isDrag, setIsDrag] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ReconciliationResult | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("matched");
  const inputRef = useRef<HTMLInputElement>(null);

  const validateFile = useCallback((f: File): boolean => {
    const ext = "." + (f.name.split(".").pop() || "").toLowerCase();
    return SUPPORTED_EXTENSIONS.has(ext);
  }, []);

  const handleFile = useCallback((f: File) => {
    const valid = validateFile(f);
    setFile(f);
    setFileValid(valid);
    setError("");
    setResult(null);
  }, [validateFile]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDrag(false);
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  }, [handleFile]);

  const handleReconcile = async () => {
    if (!file || !fileValid) return;
    setLoading(true);
    setError("");
    try {
      const form = new FormData();
      form.append("statement", file);
      if (dateFrom) form.append("date_from", dateFrom);
      if (dateTo) form.append("date_to", dateTo);
      if (selectedCompanyId) form.append("company_id", String(selectedCompanyId));

      const res = await fetch(`${API_BASE_URL}/api/v1/erp/bank-reconciliation`, {
        method: "POST",
        body: form,
      });

      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || `Error ${res.status}`);
      }
      const data: ReconciliationResult = await res.json();
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

      const summary = [
        [t("bankRecon.statementTotal"), result.statement_total],
        [t("bankRecon.ledgerTotal"), result.ledger_total],
        [t("bankRecon.difference"), result.difference],
        [t("bankRecon.statementCount"), result.statement_count],
        [t("bankRecon.ledgerCount"), result.ledger_count],
        [t("bankRecon.matchedCount"), result.matched.length],
        [t("bankRecon.aiSuggestedCount"), result.smart_matched.length],
        [t("bankRecon.bankOnlyCount"), result.statement_only.length],
        [t("bankRecon.odooOnlyCount"), result.ledger_only.length],
        [t("bankRecon.dateRangeUsed"), `${result.date_range_used.from || "—"} → ${result.date_range_used.to || "—"}`],
      ];
      const wsSummary = XLSX.utils.aoa_to_sheet(summary);
      XLSX.utils.book_append_sheet(wb, wsSummary, "Summary");

      if (result.matched.length) {
        const matchedData = result.matched.map((m) => ({
          [t("bankRecon.date")]: m.statement_txn.date,
          [`${t("bankRecon.statementSide")} ${t("bankRecon.description")}`]: m.statement_txn.description,
          [`${t("bankRecon.statementSide")} ${t("bankRecon.amount")}`]: m.statement_txn.amount,
          [`Odoo ${t("bankRecon.date")}`]: m.ledger_txn.date,
          [`Odoo ${t("bankRecon.description")}`]: m.ledger_txn.description,
          [`Odoo ${t("bankRecon.amount")}`]: m.ledger_txn.amount,
        }));
        XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(matchedData), "Matched");
      }

      if (result.smart_matched.length) {
        const aiData = result.smart_matched.map((s) => ({
          [t("bankRecon.date")]: s.statement_txn.date,
          [`${t("bankRecon.statementSide")} ${t("bankRecon.description")}`]: s.statement_txn.description,
          [`${t("bankRecon.statementSide")} ${t("bankRecon.amount")}`]: s.statement_txn.amount,
          [`Odoo ${t("bankRecon.date")}`]: s.ledger_txn.date,
          [`Odoo ${t("bankRecon.description")}`]: s.ledger_txn.description,
          [`Odoo ${t("bankRecon.amount")}`]: s.ledger_txn.amount,
          [t("bankRecon.confidence")]: s.confidence,
          [t("bankRecon.reason")]: s.reason,
        }));
        XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(aiData), "AI Suggested");
      }

      if (result.statement_only.length) {
        const bankData = result.statement_only.map((tx) => ({
          [t("bankRecon.date")]: tx.date,
          [t("bankRecon.description")]: tx.description,
          [t("bankRecon.amount")]: tx.amount,
          [t("bankRecon.rowNumber")]: tx.row_number,
        }));
        XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(bankData), "Bank Only");
      }

      if (result.ledger_only.length) {
        const odooData = result.ledger_only.map((tx) => ({
          [t("bankRecon.date")]: tx.date,
          [t("bankRecon.description")]: tx.description,
          [t("bankRecon.amount")]: tx.amount,
          [t("bankRecon.rowNumber")]: tx.row_number,
        }));
        XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(odooData), "Odoo Only");
      }

      XLSX.writeFile(wb, "bank-reconciliation.xlsx");
    } catch {
      setError("Excel export failed. Please try again.");
    }
  };

  const exportPdf = () => {
    if (!result) return;
    const w = window.open("", "_blank");
    if (!w) return;
    const rows = (arr: Transaction[], label: string) =>
      arr.length
        ? `<h3>${label}</h3><table border="1" cellpadding="4" style="border-collapse:collapse;width:100%;font-size:12px">
            <tr><th>${t("bankRecon.date")}</th><th>${t("bankRecon.description")}</th><th>${t("bankRecon.amount")}</th></tr>
            ${arr.map((tx) => `<tr><td>${tx.date}</td><td>${tx.description}</td><td>${formatAmount(tx.amount)}</td></tr>`).join("")}
          </table>`
        : "";
    const matchedRows = result.matched.length
      ? `<h3>${t("bankRecon.matched")}</h3><table border="1" cellpadding="4" style="border-collapse:collapse;width:100%;font-size:12px">
          <tr><th>${t("bankRecon.statementSide")} ${t("bankRecon.date")}</th><th>${t("bankRecon.statementSide")} ${t("bankRecon.description")}</th><th>${t("bankRecon.statementSide")} ${t("bankRecon.amount")}</th>
          <th>Odoo ${t("bankRecon.date")}</th><th>Odoo ${t("bankRecon.description")}</th><th>Odoo ${t("bankRecon.amount")}</th></tr>
          ${result.matched.map((m) => `<tr><td>${m.statement_txn.date}</td><td>${m.statement_txn.description}</td><td>${formatAmount(m.statement_txn.amount)}</td><td>${m.ledger_txn.date}</td><td>${m.ledger_txn.description}</td><td>${formatAmount(m.ledger_txn.amount)}</td></tr>`).join("")}
        </table>`
      : "";
    const html = `<!DOCTYPE html><html dir="${language === "ar" ? "rtl" : "ltr"}"><head><meta charset="utf-8"><title>Bank Reconciliation</title>
      <style>body{font-family:sans-serif;padding:20px}h2{color:#333}table{margin-bottom:20px}th{background:#f0f0f0}</style></head><body>
      <h2>${t("bankRecon.pageTitle")}</h2>
      <table border="1" cellpadding="4" style="border-collapse:collapse;font-size:13px">
        <tr><td><strong>${t("bankRecon.statementTotal")}</strong></td><td>${formatAmount(result.statement_total)}</td></tr>
        <tr><td><strong>${t("bankRecon.ledgerTotal")}</strong></td><td>${formatAmount(result.ledger_total)}</td></tr>
        <tr><td><strong>${t("bankRecon.difference")}</strong></td><td>${formatAmount(result.difference)}</td></tr>
        <tr><td><strong>${t("bankRecon.statementCount")}</strong></td><td>${result.statement_count}</td></tr>
        <tr><td><strong>${t("bankRecon.ledgerCount")}</strong></td><td>${result.ledger_count}</td></tr>
        <tr><td><strong>${t("bankRecon.dateRangeUsed")}</strong></td><td>${result.date_range_used.from || "—"} → ${result.date_range_used.to || "—"}</td></tr>
      </table>
      ${matchedRows}
      ${rows(result.statement_only, t("bankRecon.bankOnly"))}
      ${rows(result.ledger_only, t("bankRecon.systemOnly"))}
      </body></html>`;
    w.document.write(html);
    w.document.close();
    setTimeout(() => { w.print(); }, 500);
  };

  const tabs: { key: TabKey; label: string; count: number }[] = [
    { key: "matched", label: t("bankRecon.exactMatch"), count: result?.matched.length ?? 0 },
    { key: "ai_suggested", label: t("bankRecon.aiSuggested"), count: result?.smart_matched.length ?? 0 },
    { key: "bank_only", label: t("bankRecon.bankOnly"), count: result?.statement_only.length ?? 0 },
    { key: "odoo_only", label: t("bankRecon.systemOnly"), count: result?.ledger_only.length ?? 0 },
  ];

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">{t("bankRecon.pageTitle")}</h1>
        <p className="text-sm text-gray-400 mt-1">{t("bankRecon.pageSubtitle")}</p>
      </div>

      {/* Upload Section */}
      <div className="rounded-2xl border border-white/10 bg-black/30 p-6 space-y-4">
        <h2 className="text-lg font-semibold text-white">{t("bankRecon.uploadStatement")}</h2>

        {/* Drop zone */}
        <div
          onDragOver={(e) => { e.preventDefault(); setIsDrag(true); }}
          onDragLeave={() => setIsDrag(false)}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          className={`cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition-all ${
            isDrag
              ? "border-amber-400 bg-amber-500/10"
              : "border-white/20 bg-black/20 hover:border-white/30"
          }`}
        >
          <input
            ref={inputRef}
            type="file"
            className="hidden"
            accept={Array.from(SUPPORTED_EXTENSIONS).join(",")}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleFile(f);
            }}
          />
          <p className="text-white/70">{t("bankRecon.dropStatement")}</p>
          <p className="text-xs text-gray-500 mt-2">{t("bankRecon.supportedFormats")}</p>
        </div>

        {/* File info */}
        {file && (
          <div className="flex items-center gap-4 rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
            <div className="flex-1 space-y-0.5">
              <p className="text-white font-medium">{file.name}</p>
              <p className="text-gray-500">{fileSize(file.size)} &middot; {file.name.split(".").pop()?.toUpperCase()}</p>
            </div>
            <span className={`px-2 py-0.5 rounded-md text-xs font-medium border ${fileValid ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30" : "bg-red-500/20 text-red-400 border-red-500/30"}`}>
              {fileValid ? t("bankRecon.valid") : t("bankRecon.invalid")}
            </span>
          </div>
        )}

        {/* Date range */}
        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label className="block text-xs text-gray-400 mb-1">{t("bankRecon.dateFrom")}</label>
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
              className="rounded-lg bg-black/40 border border-white/10 text-white text-sm px-3 py-2 outline-none focus:border-amber-400/50" />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">{t("bankRecon.dateTo")}</label>
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
              className="rounded-lg bg-black/40 border border-white/10 text-white text-sm px-3 py-2 outline-none focus:border-amber-400/50" />
          </div>
          <button
            disabled={!file || !fileValid || loading}
            onClick={handleReconcile}
            className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-yellow-600 text-black font-semibold text-sm disabled:opacity-40 disabled:cursor-not-allowed hover:shadow-[0_0_20px_rgba(217,164,65,0.3)] transition-all"
          >
            {loading ? t("bankRecon.reconciling") : t("bankRecon.startReconciliation")}
          </button>
        </div>

        {error && (
          <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">{error}</div>
        )}
      </div>

      {/* Results */}
      {result && (
        <>
          {/* Dashboard Cards */}
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
              { label: t("bankRecon.dateRangeUsed"), value: `${result.date_range_used.from || "—"} → ${result.date_range_used.to || "—"}`, color: "text-gray-300", small: true },
            ].map((card, i) => (
              <div key={i} className="rounded-xl border border-white/10 bg-black/30 px-4 py-3">
                <p className="text-[11px] text-gray-500 uppercase tracking-wide">{card.label}</p>
                <p className={`text-lg font-bold mt-1 ${card.color} ${"small" in card ? "!text-sm" : ""}`}>{card.value}</p>
              </div>
            ))}
          </div>

          {/* Export buttons */}
          <div className="flex gap-3">
            <button onClick={exportExcel} className="px-4 py-2 rounded-lg bg-emerald-600/20 border border-emerald-500/30 text-emerald-400 text-sm font-medium hover:bg-emerald-600/30 transition-colors">
              {t("bankRecon.exportExcel")}
            </button>
            <button onClick={exportPdf} className="px-4 py-2 rounded-lg bg-sky-600/20 border border-sky-500/30 text-sky-400 text-sm font-medium hover:bg-sky-600/30 transition-colors">
              {t("bankRecon.exportPdf")}
            </button>
          </div>

          {/* Tabs */}
          <div className="flex gap-1 border-b border-white/10 pb-0">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
                  activeTab === tab.key
                    ? "bg-white/10 text-amber-400 border-b-2 border-amber-400"
                    : "text-gray-400 hover:text-white hover:bg-white/5"
                }`}
              >
                {tab.label} <span className="text-xs opacity-60">({tab.count})</span>
              </button>
            ))}
          </div>

          {/* Tab Content */}
          <div className="rounded-xl border border-white/10 bg-black/20 overflow-x-auto">
            {activeTab === "matched" && (
              result.matched.length ? (
                <table className="w-full text-sm">
                  <thead><tr className="border-b border-white/10 text-gray-400 text-xs uppercase">
                    <th className="px-3 py-2 text-start">{t("bankRecon.statementSide")} {t("bankRecon.date")}</th>
                    <th className="px-3 py-2 text-start">{t("bankRecon.statementSide")} {t("bankRecon.description")}</th>
                    <th className="px-3 py-2 text-end">{t("bankRecon.statementSide")} {t("bankRecon.amount")}</th>
                    <th className="px-3 py-2 text-start">Odoo {t("bankRecon.date")}</th>
                    <th className="px-3 py-2 text-start">Odoo {t("bankRecon.description")}</th>
                    <th className="px-3 py-2 text-end">Odoo {t("bankRecon.amount")}</th>
                    <th className="px-3 py-2 text-start">{t("bankRecon.matchType")}</th>
                  </tr></thead>
                  <tbody>
                    {result.matched.map((m, i) => (
                      <tr key={i} className="border-b border-white/5 hover:bg-white/5">
                        <td className="px-3 py-2 text-gray-300">{m.statement_txn.date}</td>
                        <td className="px-3 py-2 text-white">{m.statement_txn.description}</td>
                        <td className="px-3 py-2 text-end text-gray-300">{formatAmount(m.statement_txn.amount)}</td>
                        <td className="px-3 py-2 text-gray-300">{m.ledger_txn.date}</td>
                        <td className="px-3 py-2 text-white">{m.ledger_txn.description}</td>
                        <td className="px-3 py-2 text-end text-gray-300">{formatAmount(m.ledger_txn.amount)}</td>
                        <td className="px-3 py-2"><span className="px-2 py-0.5 rounded text-xs bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">{t("bankRecon.exactMatch")}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <p className="p-6 text-center text-gray-500">{t("bankRecon.noDiscrepancies")}</p>
            )}

            {activeTab === "ai_suggested" && (
              result.smart_matched.length ? (
                <div>
                  <p className="px-4 py-2 text-xs text-purple-400/80 bg-purple-500/5 border-b border-white/5">{t("bankRecon.noAutoApprove")}</p>
                  <table className="w-full text-sm">
                    <thead><tr className="border-b border-white/10 text-gray-400 text-xs uppercase">
                      <th className="px-3 py-2 text-start">{t("bankRecon.statementSide")} {t("bankRecon.date")}</th>
                      <th className="px-3 py-2 text-start">{t("bankRecon.statementSide")} {t("bankRecon.description")}</th>
                      <th className="px-3 py-2 text-end">{t("bankRecon.statementSide")} {t("bankRecon.amount")}</th>
                      <th className="px-3 py-2 text-start">Odoo {t("bankRecon.date")}</th>
                      <th className="px-3 py-2 text-start">Odoo {t("bankRecon.description")}</th>
                      <th className="px-3 py-2 text-end">Odoo {t("bankRecon.amount")}</th>
                      <th className="px-3 py-2 text-center">{t("bankRecon.confidence")}</th>
                      <th className="px-3 py-2 text-start">{t("bankRecon.reason")}</th>
                    </tr></thead>
                    <tbody>
                      {result.smart_matched.map((s, i) => (
                        <tr key={i} className="border-b border-white/5 hover:bg-white/5">
                          <td className="px-3 py-2 text-gray-300">{s.statement_txn.date}</td>
                          <td className="px-3 py-2 text-white">{s.statement_txn.description}</td>
                          <td className="px-3 py-2 text-end text-gray-300">{formatAmount(s.statement_txn.amount)}</td>
                          <td className="px-3 py-2 text-gray-300">{s.ledger_txn.date}</td>
                          <td className="px-3 py-2 text-white">{s.ledger_txn.description}</td>
                          <td className="px-3 py-2 text-end text-gray-300">{formatAmount(s.ledger_txn.amount)}</td>
                          <td className="px-3 py-2 text-center">
                            <span className={`px-2 py-0.5 rounded text-xs border font-medium ${confidenceBadge(s.confidence)}`}>
                              {(s.confidence * 100).toFixed(0)}%
                            </span>
                          </td>
                          <td className="px-3 py-2 text-gray-400 text-xs">{s.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <p className="p-6 text-center text-gray-500">{t("bankRecon.noDiscrepancies")}</p>
            )}

            {activeTab === "bank_only" && (
              result.statement_only.length ? (
                <table className="w-full text-sm">
                  <thead><tr className="border-b border-white/10 text-gray-400 text-xs uppercase">
                    <th className="px-3 py-2 text-start">{t("bankRecon.date")}</th>
                    <th className="px-3 py-2 text-start">{t("bankRecon.description")}</th>
                    <th className="px-3 py-2 text-end">{t("bankRecon.amount")}</th>
                    <th className="px-3 py-2 text-center">{t("bankRecon.rowNumber")}</th>
                    <th className="px-3 py-2 text-start">{t("bankRecon.suggestedAction")}</th>
                  </tr></thead>
                  <tbody>
                    {result.statement_only.map((tx, i) => (
                      <tr key={i} className="border-b border-white/5 hover:bg-white/5">
                        <td className="px-3 py-2 text-gray-300">{tx.date}</td>
                        <td className="px-3 py-2 text-white">{tx.description}</td>
                        <td className="px-3 py-2 text-end text-gray-300">{formatAmount(tx.amount)}</td>
                        <td className="px-3 py-2 text-center text-gray-500">{tx.row_number}</td>
                        <td className="px-3 py-2">
                          <span className="px-2 py-0.5 rounded text-xs bg-yellow-500/20 text-yellow-400 border border-yellow-500/30">
                            {t("bankRecon.needsReview")}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <p className="p-6 text-center text-gray-500">{t("bankRecon.noDiscrepancies")}</p>
            )}

            {activeTab === "odoo_only" && (
              result.ledger_only.length ? (
                <table className="w-full text-sm">
                  <thead><tr className="border-b border-white/10 text-gray-400 text-xs uppercase">
                    <th className="px-3 py-2 text-start">{t("bankRecon.date")}</th>
                    <th className="px-3 py-2 text-start">{t("bankRecon.description")}</th>
                    <th className="px-3 py-2 text-end">{t("bankRecon.amount")}</th>
                    <th className="px-3 py-2 text-center">{t("bankRecon.rowNumber")}</th>
                    <th className="px-3 py-2 text-start">{t("bankRecon.suggestedAction")}</th>
                  </tr></thead>
                  <tbody>
                    {result.ledger_only.map((tx, i) => (
                      <tr key={i} className="border-b border-white/5 hover:bg-white/5">
                        <td className="px-3 py-2 text-gray-300">{tx.date}</td>
                        <td className="px-3 py-2 text-white">{tx.description}</td>
                        <td className="px-3 py-2 text-end text-gray-300">{formatAmount(tx.amount)}</td>
                        <td className="px-3 py-2 text-center text-gray-500">{tx.row_number}</td>
                        <td className="px-3 py-2">
                          <span className="px-2 py-0.5 rounded text-xs bg-orange-500/20 text-orange-400 border border-orange-500/30">
                            {t("bankRecon.checkMissing")}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <p className="p-6 text-center text-gray-500">{t("bankRecon.noDiscrepancies")}</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
