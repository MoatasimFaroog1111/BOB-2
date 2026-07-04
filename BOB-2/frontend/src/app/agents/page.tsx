"use client";

import React, { useState } from "react";
import { API_BASE_URL } from "@/lib/api";
import { useLanguage } from "@/lib/LanguageContext";

type SourceType = "manual_text" | "ocr_text" | "invoice" | "receipt" | "payment_voucher" | "purchase_order" | "bank_statement" | "journal_entry" | "trial_balance" | "vendor_bill";

type AgentFinding = {
  agent: string;
  role: string;
  confidence: number;
  summary: string;
  details: Record<string, unknown>;
};

type WorkflowConflict = {
  type: string;
  severity: string;
  message: string;
};

type WorkflowResponse = {
  status: string;
  workflow: string;
  source_type: SourceType;
  extracted_signals: {
    amounts: string[];
    dates: string[];
    references: string[];
    party_candidates: string[];
  };
  agent_findings: AgentFinding[];
  conflicts: WorkflowConflict[];
  final_recommendation: {
    confidence_score: number;
    decision: string;
    auto_posted_to_erp: boolean;
    approval_required: boolean;
    summary: string;
  };
};

const SOURCE_TYPES: SourceType[] = ["manual_text", "ocr_text", "invoice", "receipt", "payment_voucher", "purchase_order", "bank_statement", "journal_entry", "trial_balance", "vendor_bill"];

const SAMPLE_TEXT = `Invoice INV-2026-0001
Supplier: Example Supplier
Date: 2026-07-04
Subtotal SAR 1000.00
VAT 15% SAR 150.00
Total SAR 1150.00`;

export default function AccountingAgentsPage() {
  const { language } = useLanguage();
  const isArabic = language === "ar";
  const [text, setText] = useState(SAMPLE_TEXT);
  const [sourceType, setSourceType] = useState<SourceType>("invoice");
  const [result, setResult] = useState<WorkflowResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const runWorkflow = async () => {
    if (text.trim().length < 8) return;
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/agents/run-accounting-workflow`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, source_type: sourceType, organization_id: 1, language: "auto" }),
      });
      if (!response.ok) throw new Error(await response.text());
      setResult((await response.json()) as WorkflowResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Workflow failed");
    } finally {
      setLoading(false);
    }
  };

  const confidenceClass = (value: number) => value >= 0.8 ? "border-green-400/40 bg-green-500/10 text-green-200" : value >= 0.6 ? "border-amber-400/40 bg-amber-500/10 text-amber-200" : "border-orange-400/40 bg-orange-500/10 text-orange-200";

  return (
    <div className="h-full overflow-auto bg-[radial-gradient(circle_at_top_right,rgba(34,211,238,0.14),transparent_35%),#050505] p-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="space-y-3">
          <span className="text-xs font-bold uppercase tracking-[0.3em] text-cyan-300">{isArabic ? "وكلاء محاسبة وتدقيق" : "Accounting and audit agents"}</span>
          <h1 className="text-4xl font-extrabold text-white">AI Accounting Agents</h1>
          <p className="max-w-4xl text-sm leading-6 text-white/60">
            {isArabic ? "حلّل نص OCR أو فاتورة أو كشف بنك عبر عدة وكلاء محاسبة. النتائج اقتراحات آمنة ولا يتم ترحيل أي قيد إلى ERP تلقائيًا." : "Analyze OCR, invoices, vouchers, and bank text through multiple accounting agents. Results are review-only and never auto-post to ERP."}
          </p>
        </header>

        <section className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_1fr]">
          <div className="rounded-3xl border border-white/10 bg-white/[0.04] p-5 shadow-2xl">
            <div className="mb-3 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <label className="text-sm font-bold text-white">{isArabic ? "النص المراد تحليله" : "Text to analyze"}</label>
              <select value={sourceType} onChange={(event) => setSourceType(event.target.value as SourceType)} className="rounded-xl border border-white/10 bg-black/50 px-3 py-2 text-xs text-white">
                {SOURCE_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
              </select>
            </div>
            <textarea value={text} onChange={(event) => setText(event.target.value)} className="min-h-[430px] w-full resize-none rounded-2xl border border-white/10 bg-black/45 p-4 text-sm leading-6 text-white outline-none focus:border-cyan-400/60" />
            <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
              <button onClick={() => setText(SAMPLE_TEXT)} className="rounded-2xl border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-sm font-bold text-amber-200 hover:bg-amber-500/20">{isArabic ? "مثال فاتورة" : "Load sample"}</button>
              <button onClick={runWorkflow} disabled={loading || text.trim().length < 8} className="rounded-2xl bg-cyan-400 px-4 py-3 text-sm font-extrabold text-black hover:bg-cyan-300 disabled:opacity-50">{loading ? (isArabic ? "جاري التحليل..." : "Running...") : (isArabic ? "تشغيل الوكلاء" : "Run Agents")}</button>
            </div>
            {error && <p className="mt-3 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-200">{error}</p>}
          </div>

          <div className="space-y-5">
            {result ? <Results result={result} confidenceClass={confidenceClass} isArabic={isArabic} /> : <div className="rounded-3xl border border-white/10 bg-white/[0.04] p-8 text-sm text-white/45">{isArabic ? "شغّل الوكلاء لعرض النتائج هنا." : "Run the agents to show results here."}</div>}
          </div>
        </section>
      </div>
    </div>
  );
}

function Results({ result, confidenceClass, isArabic }: { result: WorkflowResponse; confidenceClass: (value: number) => string; isArabic: boolean }) {
  return (
    <>
      <div className="rounded-3xl border border-amber-400/20 bg-amber-500/[0.06] p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-bold text-amber-100">{isArabic ? "التوصية النهائية" : "Final recommendation"}</h2>
          <span className={`rounded-full border px-3 py-1 text-xs font-bold ${confidenceClass(result.final_recommendation.confidence_score)}`}>{Math.round(result.final_recommendation.confidence_score * 100)}%</span>
        </div>
        <p className="mt-3 text-sm text-white/65">{result.final_recommendation.summary}</p>
        <p className="mt-2 text-xs text-amber-200/70">{result.final_recommendation.auto_posted_to_erp ? "ERP auto-posting enabled" : "No automatic ERP posting"}</p>
      </div>

      <div className="rounded-3xl border border-white/10 bg-white/[0.04] p-5">
        <h2 className="mb-4 text-lg font-bold text-white">{isArabic ? "الإشارات المستخرجة" : "Extracted signals"}</h2>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <ListCard title="Amounts" items={result.extracted_signals.amounts} />
          <ListCard title="Dates" items={result.extracted_signals.dates} />
          <ListCard title="References" items={result.extracted_signals.references} />
          <ListCard title="Parties" items={result.extracted_signals.party_candidates} />
        </div>
      </div>

      <div className="rounded-3xl border border-white/10 bg-white/[0.04] p-5">
        <h2 className="mb-4 text-lg font-bold text-white">{isArabic ? "نتائج الوكلاء" : "Agent findings"}</h2>
        <div className="space-y-3">
          {result.agent_findings.map((finding) => <AgentCard key={finding.agent} finding={finding} confidenceClass={confidenceClass} />)}
        </div>
      </div>

      <div className="rounded-3xl border border-white/10 bg-white/[0.04] p-5">
        <h2 className="mb-4 text-lg font-bold text-white">{isArabic ? "نقاط المراجعة" : "Review points"}</h2>
        {result.conflicts.length === 0 ? <p className="rounded-2xl border border-emerald-400/20 bg-emerald-500/10 p-4 text-sm text-emerald-200">{isArabic ? "لا توجد تعارضات رئيسية." : "No major conflicts."}</p> : result.conflicts.map((conflict) => <div key={`${conflict.type}-${conflict.message}`} className="mb-3 rounded-2xl border border-orange-400/20 bg-orange-500/10 p-4"><b className="text-orange-100">{conflict.type}</b><p className="mt-2 text-sm text-white/65">{conflict.message}</p></div>)}
      </div>
    </>
  );
}

function AgentCard({ finding, confidenceClass }: { finding: AgentFinding; confidenceClass: (value: number) => string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/30 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h3 className="font-bold text-white">{finding.agent}</h3><p className="text-xs text-white/45">{finding.role}</p></div>
        <span className={`rounded-full border px-3 py-1 text-xs font-bold ${confidenceClass(finding.confidence)}`}>{Math.round(finding.confidence * 100)}%</span>
      </div>
      <p className="mt-3 text-sm text-white/60">{finding.summary}</p>
      <pre className="mt-3 max-h-44 overflow-auto rounded-xl bg-black/50 p-3 text-[11px] leading-5 text-white/45">{JSON.stringify(finding.details, null, 2)}</pre>
    </div>
  );
}

function ListCard({ title, items }: { title: string; items: string[] }) {
  return <div className="rounded-2xl border border-white/10 bg-black/30 p-4"><p className="text-xs font-bold uppercase tracking-[0.2em] text-white/35">{title}</p><p className="mt-3 break-words text-sm text-white/70">{items.length ? items.join(", ") : "—"}</p></div>;
}
