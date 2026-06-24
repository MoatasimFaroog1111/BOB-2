"use client";

import React, { useState } from "react";
import { API_BASE_URL } from "@/lib/api";
import { useLanguage } from "@/lib/LanguageContext";

type Match = { id: number; match_type: string; confidence_score: number; similarity_score: number; explanation: string; status: string };
type Suggestion = { id: number; status: string; confidence_score: number; explanation: string; debit_account: { name: string; reason: string }; credit_account: { name: string; reason: string }; vat_account?: { name: string; reason: string } | null };
type AnalysisResponse = { embedding: { id: number; model: string; dimension: number; confidence_score: number; classification: { document_type: string; detected_party?: string | null; vat_relevant: boolean; financial_categories: string[] }; text_preview: string }; suggested_matches: Match[]; journal_entry_suggestion: Suggestion; audit_safe: { auto_posted_to_erp: boolean; approval_required: boolean } };

export default function AccountingAIMatchingPage() {
  const { t } = useLanguage();
  const [text, setText] = useState("");
  const [sourceType, setSourceType] = useState("manual_text");
  const [result, setResult] = useState<AnalysisResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const analyze = async () => {
    if (!text.trim()) return;
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/accounting-ai/analyze`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, source_type: sourceType }) });
      if (!res.ok) throw new Error(await res.text());
      setResult(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setLoading(false);
    }
  };

  const updateStatus = async (entity: "matches" | "suggestions", id: number, status: "approved" | "rejected") => {
    const res = await fetch(`${API_BASE_URL}/api/v1/accounting-ai/${entity}/${id}/status`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) });
    if (!res.ok) return setError(await res.text());
    if (entity === "matches") setResult((prev) => prev ? { ...prev, suggested_matches: prev.suggested_matches.map((m) => m.id === id ? { ...m, status } : m) } : prev);
    if (entity === "suggestions") setResult((prev) => prev ? { ...prev, journal_entry_suggestion: { ...prev.journal_entry_suggestion, status } } : prev);
  };

  const confidenceClass = (value: number) => value >= 0.8 ? "text-green-300 border-green-400/40 bg-green-500/10" : value >= 0.6 ? "text-amber-300 border-amber-400/40 bg-amber-500/10" : "text-orange-300 border-orange-400/40 bg-orange-500/10";

  return (
    <div className="h-full overflow-auto p-8 bg-[radial-gradient(circle_at_top_right,rgba(217,164,65,0.12),transparent_35%),#050505]">
      <div className="max-w-7xl mx-auto space-y-6">
        <header className="flex flex-col gap-2">
          <span className="text-xs font-bold text-amber-300 uppercase tracking-[0.3em]">{t("accountingAI.eyebrow")}</span>
          <h1 className="text-3xl font-extrabold text-white">{t("accountingAI.title")}</h1>
          <p className="text-sm text-white/55 max-w-3xl">{t("accountingAI.subtitle")}</p>
        </header>
        <section className="grid grid-cols-1 xl:grid-cols-[1fr_1.1fr] gap-5">
          <div className="rounded-3xl border border-white/10 bg-white/[0.04] p-5 shadow-2xl">
            <div className="flex items-center justify-between mb-3">
              <label className="text-sm font-bold text-white">{t("accountingAI.extractedText")}</label>
              <select value={sourceType} onChange={(e) => setSourceType(e.target.value)} className="bg-black/50 border border-white/10 rounded-xl px-3 py-2 text-xs text-white">
                {["manual_text", "ocr_text", "invoice", "receipt", "payment_voucher", "purchase_order", "bank_statement", "journal_entry", "trial_balance", "vendor_bill"].map((type) => <option key={type} value={type}>{type}</option>)}
              </select>
            </div>
            <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder={t("accountingAI.placeholder")} className="min-h-[420px] w-full resize-none rounded-2xl border border-white/10 bg-black/45 p-4 text-sm text-white outline-none focus:border-amber-400/60" />
            <button onClick={analyze} disabled={loading || text.trim().length < 8} className="mt-4 w-full rounded-2xl bg-amber-500 px-4 py-3 text-sm font-extrabold text-black disabled:opacity-50">{loading ? t("accountingAI.analyzing") : t("accountingAI.analyze")}</button>
            {error && <p className="mt-3 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-200">{error}</p>}
          </div>
          <div className="space-y-5">
            {result ? <Results result={result} updateStatus={updateStatus} confidenceClass={confidenceClass} t={t} /> : <div className="rounded-3xl border border-white/10 bg-white/[0.04] p-8 text-white/45">{t("accountingAI.emptyState")}</div>}
          </div>
        </section>
      </div>
    </div>
  );
}

function Results({ result, updateStatus, confidenceClass, t }: { result: AnalysisResponse; updateStatus: (entity: "matches" | "suggestions", id: number, status: "approved" | "rejected") => void; confidenceClass: (value: number) => string; t: (key: string) => string }) {
  return <>
    <div className="rounded-3xl border border-cyan-400/20 bg-cyan-500/[0.06] p-5"><div className="flex flex-wrap items-center gap-3 justify-between"><h2 className="text-lg font-bold text-cyan-100">{t("accountingAI.classification")}</h2><span className={`rounded-full border px-3 py-1 text-xs font-bold ${confidenceClass(result.embedding.confidence_score)}`}>{Math.round(result.embedding.confidence_score * 100)}%</span></div><dl className="mt-4 grid grid-cols-2 gap-3 text-sm"><div><dt className="text-white/45">{t("accountingAI.docType")}</dt><dd className="font-bold text-white">{result.embedding.classification.document_type}</dd></div><div><dt className="text-white/45">{t("accountingAI.party")}</dt><dd className="font-bold text-white">{result.embedding.classification.detected_party || "—"}</dd></div><div><dt className="text-white/45">VAT</dt><dd className="font-bold text-white">{result.embedding.classification.vat_relevant ? t("accountingAI.yes") : t("accountingAI.no")}</dd></div><div><dt className="text-white/45">Embedding</dt><dd className="font-bold text-white">{result.embedding.dimension}D</dd></div></dl><p className="mt-3 text-xs text-white/45 break-all">{result.embedding.model}</p></div>
    <div className="rounded-3xl border border-white/10 bg-white/[0.04] p-5"><h2 className="text-lg font-bold text-white mb-3">{t("accountingAI.suggestedMatches")}</h2>{result.suggested_matches.length === 0 ? <p className="text-sm text-white/45">{t("accountingAI.noMatches")}</p> : result.suggested_matches.map((match) => <div key={match.id} className="mb-3 rounded-2xl border border-white/10 bg-black/30 p-4"><div className="flex justify-between gap-3"><b className="text-white">{match.match_type}</b><span className={`rounded-full border px-2 py-1 text-xs ${confidenceClass(match.confidence_score)}`}>{Math.round(match.confidence_score * 100)}%</span></div><p className="mt-2 text-sm text-white/60">{match.explanation}</p><div className="mt-3 flex gap-2"><button onClick={() => updateStatus("matches", match.id, "approved")} className="rounded-xl bg-green-500/20 px-3 py-1.5 text-xs font-bold text-green-200">{t("accountingAI.approve")}</button><button onClick={() => updateStatus("matches", match.id, "rejected")} className="rounded-xl bg-red-500/20 px-3 py-1.5 text-xs font-bold text-red-200">{t("accountingAI.reject")}</button><span className="text-xs text-white/40 self-center">{match.status}</span></div></div>)}</div>
    <div className="rounded-3xl border border-amber-400/20 bg-amber-500/[0.06] p-5"><div className="flex justify-between gap-3"><h2 className="text-lg font-bold text-amber-100">{t("accountingAI.journalSuggestion")}</h2><span className="rounded-full border border-amber-400/40 px-3 py-1 text-xs text-amber-200">{result.journal_entry_suggestion.status}</span></div><p className="mt-2 text-sm text-white/60">{result.journal_entry_suggestion.explanation}</p><div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3"><AccountCard title={t("accountingAI.debit")} account={result.journal_entry_suggestion.debit_account} /><AccountCard title={t("accountingAI.credit")} account={result.journal_entry_suggestion.credit_account} />{result.journal_entry_suggestion.vat_account && <AccountCard title="VAT" account={result.journal_entry_suggestion.vat_account} />}</div><div className="mt-4 flex gap-2"><button onClick={() => updateStatus("suggestions", result.journal_entry_suggestion.id, "approved")} className="rounded-xl bg-green-500/20 px-4 py-2 text-xs font-bold text-green-200">{t("accountingAI.approveDraft")}</button><button onClick={() => updateStatus("suggestions", result.journal_entry_suggestion.id, "rejected")} className="rounded-xl bg-red-500/20 px-4 py-2 text-xs font-bold text-red-200">{t("accountingAI.reject")}</button></div><p className="mt-3 text-xs text-amber-200/70">{t("accountingAI.auditSafe")}</p></div>
  </>;
}

function AccountCard({ title, account }: { title: string; account: { name: string; reason: string } }) {
  return <div className="rounded-2xl border border-white/10 bg-black/30 p-4"><p className="text-xs text-white/45">{title}</p><h3 className="mt-1 font-bold text-white">{account.name}</h3><p className="mt-2 text-xs text-white/50">{account.reason}</p></div>;
}
