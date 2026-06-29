"use client";

import { useState } from "react";

interface Transaction {
  date: string;
  hijri_date?: string;
  description: string;
  main_description?: string;
  details?: string[];
  amount: number;
  debit?: number | null;
  credit?: number | null;
  balance?: number | null;
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
  statement_only: Transaction[];
  ledger_only: Transaction[];
  matched: MatchedPair[];
  smart_matched: SmartMatch[];
  statement_total: number;
  ledger_total: number;
  difference: number;
  statement_count: number;
  ledger_count: number;
}

type ResultView = "matched" | "statement_only" | "google_only" | "difference";

function fmt(value?: number | null) {
  const n = Number(value || 0);
  return n.toLocaleString("en-SA", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function amountColor(value?: number | null) {
  const n = Number(value || 0);
  if (n > 0) return "text-emerald-400";
  if (n < 0) return "text-rose-400";
  return "text-white/50";
}

function downloadCSV(filename: string, rows: string[][]) {
  const csv = rows.map(row => row.map(cell => `"${String(cell ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
  const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function TxnCard({ txn, label, isAr }: { txn: Transaction; label: string; isAr: boolean }) {
  return (
    <div className="rounded-xl border border-white/10 bg-black/25 p-3 text-[11px] hover:bg-white/5 transition-colors">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="rounded-full bg-white/10 px-2 py-0.5 text-white/60">{label}</span>
            <span className="font-mono text-white/60">{txn.date || "—"}</span>
            {txn.hijri_date && <span className="font-mono text-white/40">{txn.hijri_date}</span>}
          </div>
          <p className="mt-2 font-bold text-white leading-relaxed">{txn.main_description || txn.description || "—"}</p>
          {txn.details && txn.details.length > 0 && (
            <details className="mt-2 text-white/55">
              <summary className="cursor-pointer text-blue-300 font-semibold">{isAr ? "تفاصيل إضافية" : "More details"}</summary>
              <div className="mt-2 space-y-1">
                {txn.details.map((detail, idx) => <div key={idx} className="border-b border-white/5 pb-1">{detail}</div>)}
              </div>
            </details>
          )}
        </div>
        <div className={`shrink-0 text-end font-mono text-sm font-bold ${amountColor(txn.amount)}`}>
          {fmt(txn.amount)}
          <div className="text-[9px] text-white/40">SAR</div>
        </div>
      </div>
    </div>
  );
}

export default function ReconciliationResultsPanel({ result, isAr }: { result: ReconciliationResult; isAr: boolean }) {
  const matchedCount = result.matched.length + result.smart_matched.length;
  const isBalanced = Math.abs(result.difference) < 0.01;
  const [activeView, setActiveView] = useState<ResultView>("matched");
  const [processedViews, setProcessedViews] = useState<Record<ResultView, boolean>>({
    matched: false,
    statement_only: false,
    google_only: false,
    difference: false,
  });
  const [notice, setNotice] = useState("");

  const meta: Record<ResultView, { icon: string; title: string; count: string | number; border: string; text: string; hint: string }> = {
    matched: {
      icon: "✅",
      title: isAr ? "متطابق" : "Matched",
      count: matchedCount,
      border: "border-emerald-500/40",
      text: "text-emerald-300",
      hint: isAr ? "اضغط لعرض العمليات المتطابقة واعتمادها" : "Click to approve matched rows",
    },
    statement_only: {
      icon: "📄",
      title: isAr ? "في الكشف فقط" : "Statement only",
      count: result.statement_only.length,
      border: "border-amber-500/40",
      text: "text-amber-300",
      hint: isAr ? "اضغط لمعالجة العمليات غير الموجودة في Google" : "Click to process rows missing in Google",
    },
    google_only: {
      icon: "🟦",
      title: isAr ? "في Google فقط" : "Google only",
      count: result.ledger_only.length,
      border: "border-rose-500/40",
      text: "text-rose-300",
      hint: isAr ? "اضغط لمراجعة العمليات الموجودة في Google فقط" : "Click to review Google-only rows",
    },
    difference: {
      icon: isBalanced ? "🟢" : "⚠️",
      title: isAr ? "الفرق" : "Difference",
      count: fmt(result.difference),
      border: isBalanced ? "border-emerald-500/40" : "border-rose-500/40",
      text: isBalanced ? "text-emerald-300" : "text-rose-300",
      hint: isAr ? "اضغط لتحليل الفرق والإجراءات المطلوبة" : "Click to analyze difference",
    },
  };

  const buildRows = () => {
    const header = ["Group", "Source", "Date", "Description", "Amount", "Debit", "Credit", "Balance", "Confidence", "Reason"];
    if (activeView === "matched") {
      const exact = result.matched.flatMap((p, i) => [
        ["Matched", "Statement", p.statement_txn.date, p.statement_txn.description, fmt(p.statement_txn.amount), fmt(p.statement_txn.debit || 0), fmt(p.statement_txn.credit || 0), p.statement_txn.balance != null ? fmt(p.statement_txn.balance) : "", "100%", `Pair ${i + 1}`],
        ["Matched", "Google", p.ledger_txn.date, p.ledger_txn.description, fmt(p.ledger_txn.amount), fmt(p.ledger_txn.debit || 0), fmt(p.ledger_txn.credit || 0), p.ledger_txn.balance != null ? fmt(p.ledger_txn.balance) : "", "100%", `Pair ${i + 1}`],
      ]);
      const smart = result.smart_matched.flatMap((p, i) => [
        ["Smart matched", "Statement", p.statement_txn.date, p.statement_txn.description, fmt(p.statement_txn.amount), fmt(p.statement_txn.debit || 0), fmt(p.statement_txn.credit || 0), p.statement_txn.balance != null ? fmt(p.statement_txn.balance) : "", `${Math.round(p.confidence * 100)}%`, p.reason || `Smart ${i + 1}`],
        ["Smart matched", "Google", p.ledger_txn.date, p.ledger_txn.description, fmt(p.ledger_txn.amount), fmt(p.ledger_txn.debit || 0), fmt(p.ledger_txn.credit || 0), p.ledger_txn.balance != null ? fmt(p.ledger_txn.balance) : "", `${Math.round(p.confidence * 100)}%`, p.reason || `Smart ${i + 1}`],
      ]);
      return [header, ...exact, ...smart];
    }
    if (activeView === "statement_only") {
      return [header, ...result.statement_only.map(txn => ["Statement only", "Statement", txn.date, txn.description, fmt(txn.amount), fmt(txn.debit || 0), fmt(txn.credit || 0), txn.balance != null ? fmt(txn.balance) : "", "", isAr ? "تحتاج إضافة أو مراجعة في Google" : "Needs add or review in Google"] )];
    }
    if (activeView === "google_only") {
      return [header, ...result.ledger_only.map(txn => ["Google only", "Google", txn.date, txn.description, fmt(txn.amount), fmt(txn.debit || 0), fmt(txn.credit || 0), txn.balance != null ? fmt(txn.balance) : "", "", isAr ? "تحتاج مراجعة مقابل الكشف" : "Needs review against statement"] )];
    }
    return [["Metric", "Value"], ["Statement total", fmt(result.statement_total)], ["Google total", fmt(result.ledger_total)], ["Difference", fmt(result.difference)], ["Matched count", String(matchedCount)], ["Statement only count", String(result.statement_only.length)], ["Google only count", String(result.ledger_only.length)]];
  };

  const exportCurrent = () => {
    downloadCSV(`reconciliation_${activeView}_${new Date().toISOString().slice(0, 10)}.csv`, buildRows());
    setNotice(isAr ? "تم تجهيز ملف CSV للمعالجة." : "CSV exported for processing.");
  };

  const copyCurrent = async () => {
    if (!navigator.clipboard) return;
    await navigator.clipboard.writeText(buildRows().map(row => row.join("\t")).join("\n"));
    setNotice(isAr ? "تم نسخ التفاصيل." : "Details copied.");
  };

  const markProcessed = () => {
    setProcessedViews(prev => ({ ...prev, [activeView]: true }));
    setNotice(isAr ? "تم تحديد هذه المجموعة كمراجعة/معالجة داخل التقرير." : "This group was marked reviewed/processed in the report.");
  };

  const actionLabel = () => {
    if (activeView === "matched") return isAr ? "اعتماد المتطابق" : "Approve matches";
    if (activeView === "statement_only") return isAr ? "تحديد كجاهزة للإضافة" : "Mark ready to add";
    if (activeView === "google_only") return isAr ? "تحديد كجاهزة للمراجعة" : "Mark ready for review";
    return isAr ? "تحديد الفرق كمراجع" : "Mark difference reviewed";
  };

  const current = meta[activeView];

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {(Object.keys(meta) as ResultView[]).map(view => {
          const item = meta[view];
          const active = activeView === view;
          return (
            <button key={view} onClick={() => { setActiveView(view); setNotice(""); }} className={`wood-card !p-3 text-start border transition-all hover:-translate-y-0.5 hover:bg-white/5 ${item.border} ${active ? "ring-2 ring-amber-400/70 bg-white/5" : ""}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-2xl">{item.icon}</span>
                {processedViews[view] && <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[9px] text-emerald-300">{isAr ? "تمت المراجعة" : "Reviewed"}</span>}
              </div>
              <p className="mt-2 text-[10px] text-white/50">{item.title}</p>
              <p className={`text-2xl font-bold tabular-nums ${item.text}`}>{item.count}</p>
              <p className="mt-1 text-[9px] text-white/40 leading-relaxed">{item.hint}</p>
            </button>
          );
        })}
      </div>

      <div className={`rounded-xl border p-3 ${isBalanced ? "border-emerald-500/30 bg-emerald-500/10" : "border-amber-500/30 bg-amber-500/10"}`}>
        <p className="font-bold text-sm text-white">{isBalanced ? (isAr ? "✅ نتيجة المطابقة: لا يوجد فرق" : "✅ No difference") : (isAr ? "⚠️ نتيجة المطابقة: يوجد فرق يحتاج مراجعة" : "⚠️ Review needed")}</p>
        <p className="text-[11px] text-white/60 mt-1">{isAr ? "اضغط على أي بطاقة أعلاه لفتح تفاصيلها ومعالجتها." : "Click any card above to open its detail panel and processing actions."}</p>
      </div>

      <div className={`rounded-2xl border ${current.border} bg-black/25 overflow-hidden`}>
        <div className="p-3 border-b border-white/10 flex flex-col md:flex-row md:items-center md:justify-between gap-3">
          <div>
            <h4 className={`text-base font-bold ${current.text}`}>{current.icon} {current.title}</h4>
            <p className="text-[10px] text-white/50 mt-1">
              {activeView === "matched" && (isAr ? "هذه العمليات تمت مطابقتها. الإجراء المطلوب: اعتمادها وحفظ التقرير." : "Matched rows. Required action: approve and keep report.")}
              {activeView === "statement_only" && (isAr ? "هذه العمليات موجودة في الكشف فقط. الإجراء المطلوب: إضافتها أو مراجعتها في Google/النظام." : "Rows exist only in statement. Required action: add or review in Google/system.")}
              {activeView === "google_only" && (isAr ? "هذه العمليات موجودة في Google فقط. الإجراء المطلوب: مراجعة السند أو التاريخ أو المبلغ." : "Rows exist only in Google. Required action: review support/date/amount.")}
              {activeView === "difference" && (isAr ? "هذا تحليل الفرق النهائي بين الكشف وGoogle." : "Final difference analysis between statement and Google.")}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button onClick={markProcessed} className="px-3 py-1.5 rounded-lg bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 text-xs font-bold">✅ {actionLabel()}</button>
            <button onClick={exportCurrent} className="px-3 py-1.5 rounded-lg bg-blue-500/15 border border-blue-500/40 text-blue-300 text-xs font-bold">📊 {isAr ? "تصدير للمعالجة" : "Export"}</button>
            <button onClick={copyCurrent} className="px-3 py-1.5 rounded-lg bg-purple-500/15 border border-purple-500/40 text-purple-300 text-xs font-bold">📋 {isAr ? "نسخ التفاصيل" : "Copy"}</button>
            <button onClick={() => window.print()} className="px-3 py-1.5 rounded-lg bg-rose-500/15 border border-rose-500/40 text-rose-300 text-xs font-bold">🖨️ {isAr ? "طباعة" : "Print"}</button>
          </div>
        </div>

        {notice && <div className="mx-3 mt-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-2 text-[11px] text-emerald-300">{notice}</div>}

        <div className="p-3 space-y-3 max-h-[520px] overflow-auto">
          {activeView === "matched" && (
            <div className="space-y-3">
              {result.matched.length === 0 && result.smart_matched.length === 0 && <p className="text-white/40">{isAr ? "لا توجد عمليات متطابقة." : "No matched transactions."}</p>}
              {result.matched.map((pair, idx) => (
                <div key={`m-${idx}`} className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3">
                  <div className="mb-2 flex items-center justify-between gap-2"><span className="font-bold text-emerald-300">✅ {isAr ? "مطابقة مباشرة" : "Exact match"} #{idx + 1}</span><span className="font-mono text-emerald-300">100%</span></div>
                  <div className="grid md:grid-cols-2 gap-2"><TxnCard txn={pair.statement_txn} label={isAr ? "الكشف" : "Statement"} isAr={isAr} /><TxnCard txn={pair.ledger_txn} label="Google" isAr={isAr} /></div>
                </div>
              ))}
              {result.smart_matched.map((pair, idx) => (
                <div key={`s-${idx}`} className="rounded-xl border border-purple-500/20 bg-purple-500/5 p-3">
                  <div className="mb-2 flex items-center justify-between gap-2"><span className="font-bold text-purple-300">🧠 {isAr ? "مطابقة ذكية" : "Smart match"} #{idx + 1}</span><span className="font-mono text-purple-300">{Math.round(pair.confidence * 100)}%</span></div>
                  <div className="grid md:grid-cols-2 gap-2"><TxnCard txn={pair.statement_txn} label={isAr ? "الكشف" : "Statement"} isAr={isAr} /><TxnCard txn={pair.ledger_txn} label="Google" isAr={isAr} /></div>
                  {pair.reason && <p className="mt-2 text-[10px] text-white/50">{pair.reason}</p>}
                </div>
              ))}
            </div>
          )}

          {activeView === "statement_only" && <div className="space-y-2">{result.statement_only.length === 0 ? <p className="text-white/40">{isAr ? "لا توجد عمليات في الكشف فقط." : "No statement-only rows."}</p> : result.statement_only.map((txn, idx) => <TxnCard key={idx} txn={txn} label={isAr ? "الكشف فقط" : "Statement only"} isAr={isAr} />)}</div>}

          {activeView === "google_only" && <div className="space-y-2">{result.ledger_only.length === 0 ? <p className="text-white/40">{isAr ? "لا توجد عمليات في Google فقط." : "No Google-only rows."}</p> : result.ledger_only.map((txn, idx) => <TxnCard key={idx} txn={txn} label={isAr ? "Google فقط" : "Google only"} isAr={isAr} />)}</div>}

          {activeView === "difference" && (
            <div className="space-y-3">
              <div className="grid md:grid-cols-3 gap-2">
                <div className="rounded-xl border border-white/10 bg-black/20 p-3"><p className="text-[10px] text-white/50">{isAr ? "إجمالي الكشف" : "Statement total"}</p><p className="text-xl font-bold text-amber-300 font-mono">{fmt(result.statement_total)}</p></div>
                <div className="rounded-xl border border-white/10 bg-black/20 p-3"><p className="text-[10px] text-white/50">{isAr ? "إجمالي Google" : "Google total"}</p><p className="text-xl font-bold text-blue-300 font-mono">{fmt(result.ledger_total)}</p></div>
                <div className="rounded-xl border border-white/10 bg-black/20 p-3"><p className="text-[10px] text-white/50">{isAr ? "الفرق" : "Difference"}</p><p className={`text-xl font-bold font-mono ${isBalanced ? "text-emerald-300" : "text-rose-300"}`}>{fmt(result.difference)}</p></div>
              </div>
              <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-3 text-[11px] text-white/70 leading-relaxed">
                <p className="font-bold text-amber-300 mb-1">{isAr ? "المعالجة المقترحة" : "Suggested processing"}</p>
                <p>{isAr ? "ابدأ بمراجعة عمليات الكشف فقط وعمليات Google فقط. غالبًا الفرق ناتج عن عمليات لم تُسجل، عمليات مكررة، تاريخ خارج الفترة، أو اختلاف في الإشارة مدين/دائن." : "Start by reviewing statement-only and Google-only rows. Difference is usually caused by missing entries, duplicates, out-of-period dates, or debit/credit sign differences."}</p>
              </div>
              <div className="grid md:grid-cols-2 gap-3">
                <div className="space-y-2"><p className="font-bold text-amber-300">📄 {isAr ? "عمليات الكشف فقط" : "Statement only"}</p>{result.statement_only.map((txn, idx) => <TxnCard key={idx} txn={txn} label={isAr ? "الكشف" : "Statement"} isAr={isAr} />)}</div>
                <div className="space-y-2"><p className="font-bold text-rose-300">🟦 {isAr ? "عمليات Google فقط" : "Google only"}</p>{result.ledger_only.map((txn, idx) => <TxnCard key={idx} txn={txn} label="Google" isAr={isAr} />)}</div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
