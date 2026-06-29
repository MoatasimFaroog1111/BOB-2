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
  ai_suggested_account?: string;
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

type ResultView = "matched" | "statement_only" | "ledger_only" | "difference";

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

function cleanText(value?: string) {
  return (value || "").toLowerCase().replace(/[أإآ]/g, "ا").replace(/ى/g, "ي").replace(/ة/g, "ه");
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

function suggestCounterAccount(txn: Transaction) {
  const text = cleanText(`${txn.description} ${(txn.details || []).join(" ")} ${txn.ai_suggested_account || ""}`);
  if (txn.ai_suggested_account) {
    return { account: txn.ai_suggested_account, confidence: 82, source: "AI / NLP" };
  }
  if (/رسوم|عموله|charge|fee|commission|bank charge/.test(text)) {
    return { account: "مصروفات بنكية", confidence: 74, source: "NLP keyword" };
  }
  if (/راتب|رواتب|salary|payroll|wps/.test(text)) {
    return { account: "مصروفات الرواتب والأجور", confidence: 72, source: "NLP keyword" };
  }
  if (/مورد|vendor|supplier|فاتوره|bill|purchase|سداد|sadad/.test(text)) {
    return { account: "الموردون / مصروفات تحت التسوية", confidence: 68, source: "Semantic hint" };
  }
  if (/عميل|customer|client|تحصيل|ايراد|revenue|receipt|deposit|ايداع/.test(text)) {
    return { account: "العملاء / إيرادات تحت التسوية", confidence: 68, source: "Semantic hint" };
  }
  if (/ضريبه|vat|tax|زكاه|زكاة/.test(text)) {
    return { account: "ضرائب ورسوم حكومية", confidence: 66, source: "NLP keyword" };
  }
  if (/ايجار|rent|lease/.test(text)) {
    return { account: "مصروفات الإيجار", confidence: 64, source: "NLP keyword" };
  }
  return { account: "حساب وسيط للمطابقة - يحتاج اعتماد", confidence: 45, source: "Fallback" };
}

function buildJournalLines(txn: Transaction, bankAccountLabel: string) {
  const amount = Math.abs(Number(txn.amount || txn.credit || txn.debit || 0));
  const isDeposit = Number(txn.amount || 0) > 0 || (Number(txn.credit || 0) > 0 && Number(txn.debit || 0) === 0);
  const suggestion = suggestCounterAccount(txn);
  const bank = bankAccountLabel || "الحساب البنكي المختار";
  const memo = txn.main_description || txn.description || "عملية من كشف البنك";

  if (isDeposit) {
    return {
      type: "deposit",
      amount,
      suggestion,
      lines: [
        { account: bank, debit: amount, credit: 0, memo },
        { account: suggestion.account, debit: 0, credit: amount, memo },
      ],
    };
  }
  return {
    type: "payment",
    amount,
    suggestion,
    lines: [
      { account: suggestion.account, debit: amount, credit: 0, memo },
      { account: bank, debit: 0, credit: amount, memo },
    ],
  };
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

function SuggestedEntryCard({ txn, index, isAr, bankAccountLabel }: { txn: Transaction; index: number; isAr: boolean; bankAccountLabel: string }) {
  const draft = buildJournalLines(txn, bankAccountLabel);
  return (
    <div className="rounded-xl border border-cyan-500/25 bg-cyan-500/5 p-3 space-y-3">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <p className="font-bold text-cyan-300">🧾 {isAr ? "قيد مقترح للعملية" : "Suggested journal entry"} #{index + 1}</p>
          <p className="text-[10px] text-white/55 mt-1">{txn.date} — {txn.main_description || txn.description}</p>
        </div>
        <div className="text-end">
          <p className="font-mono text-amber-300 font-bold">{fmt(draft.amount)} SAR</p>
          <p className="text-[9px] text-white/45">{draft.type === "deposit" ? (isAr ? "إيداع" : "Deposit") : (isAr ? "تحويل صادر / صرف" : "Payment")}</p>
        </div>
      </div>
      <div className="rounded-lg border border-white/10 overflow-hidden">
        <table className="w-full text-[10px]">
          <thead className="bg-white/5 text-white/60">
            <tr>
              <th className="p-2 text-right">{isAr ? "الحساب" : "Account"}</th>
              <th className="p-2 text-center">{isAr ? "مدين" : "Debit"}</th>
              <th className="p-2 text-center">{isAr ? "دائن" : "Credit"}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {draft.lines.map((line, idx) => (
              <tr key={idx}>
                <td className="p-2 text-white font-semibold">{line.account}</td>
                <td className="p-2 text-center font-mono text-emerald-300">{line.debit ? fmt(line.debit) : "—"}</td>
                <td className="p-2 text-center font-mono text-rose-300">{line.credit ? fmt(line.credit) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="rounded-lg bg-black/20 border border-white/10 p-2 text-[10px] text-white/60">
        {isAr ? "الحساب المقابل مقترح بطريقة مطابقة دلالية بالوصف NLP / Semantic Matching. لا يتم الترحيل إلا بعد الاعتماد." : "Counter account suggested using NLP / Semantic Matching. Nothing is posted until approval."}
        <span className="ms-2 text-cyan-300 font-mono">{draft.suggestion.confidence}%</span>
      </div>
    </div>
  );
}

export default function ReconciliationResultsPanel({ result, isAr, bankAccountLabel = "" }: { result: ReconciliationResult; isAr: boolean; bankAccountLabel?: string }) {
  const matchedCount = result.matched.length + result.smart_matched.length;
  const isBalanced = Math.abs(result.difference) < 0.01;
  const [activeView, setActiveView] = useState<ResultView>("matched");
  const [showJournalDrafts, setShowJournalDrafts] = useState(false);
  const [processedViews, setProcessedViews] = useState<Record<ResultView, boolean>>({ matched: false, statement_only: false, ledger_only: false, difference: false });
  const [notice, setNotice] = useState("");

  const meta: Record<ResultView, { icon: string; title: string; count: string | number; border: string; text: string; hint: string }> = {
    matched: { icon: "✅", title: isAr ? "متطابق" : "Matched", count: matchedCount, border: "border-emerald-500/40", text: "text-emerald-300", hint: isAr ? "اضغط لعرض العمليات المتطابقة واعتمادها" : "Click to approve matched rows" },
    statement_only: { icon: "📄", title: isAr ? "المسجلة في كشف البنك فقط" : "Recorded in bank statement only", count: result.statement_only.length, border: "border-amber-500/40", text: "text-amber-300", hint: isAr ? "اضغط لعرضها ثم إنشاء قيد مقترح" : "Click to show and prepare suggested entries" },
    ledger_only: { icon: "📚", title: isAr ? "المسجلة في الدفاتر فقط" : "Recorded in books only", count: result.ledger_only.length, border: "border-rose-500/40", text: "text-rose-300", hint: isAr ? "اضغط لمراجعة العمليات غير الموجودة في كشف البنك" : "Click to review rows missing from bank statement" },
    difference: { icon: isBalanced ? "🟢" : "⚠️", title: isAr ? "الفرق" : "Difference", count: fmt(result.difference), border: isBalanced ? "border-emerald-500/40" : "border-rose-500/40", text: isBalanced ? "text-emerald-300" : "text-rose-300", hint: isAr ? "اضغط لتحليل الفرق والإجراءات المطلوبة" : "Click to analyze difference" },
  };

  const buildRows = () => {
    const header = ["Group", "Source", "Date", "Description", "Amount", "Debit", "Credit", "Balance", "Confidence", "Reason"];
    if (activeView === "matched") {
      const exact = result.matched.flatMap((p, i) => [["Matched", "Bank statement", p.statement_txn.date, p.statement_txn.description, fmt(p.statement_txn.amount), fmt(p.statement_txn.debit || 0), fmt(p.statement_txn.credit || 0), p.statement_txn.balance != null ? fmt(p.statement_txn.balance) : "", "100%", `Pair ${i + 1}`], ["Matched", "Accounting books", p.ledger_txn.date, p.ledger_txn.description, fmt(p.ledger_txn.amount), fmt(p.ledger_txn.debit || 0), fmt(p.ledger_txn.credit || 0), p.ledger_txn.balance != null ? fmt(p.ledger_txn.balance) : "", "100%", `Pair ${i + 1}`]]);
      const smart = result.smart_matched.flatMap((p, i) => [["Smart matched", "Bank statement", p.statement_txn.date, p.statement_txn.description, fmt(p.statement_txn.amount), fmt(p.statement_txn.debit || 0), fmt(p.statement_txn.credit || 0), p.statement_txn.balance != null ? fmt(p.statement_txn.balance) : "", `${Math.round(p.confidence * 100)}%`, p.reason || `Smart ${i + 1}`], ["Smart matched", "Accounting books", p.ledger_txn.date, p.ledger_txn.description, fmt(p.ledger_txn.amount), fmt(p.ledger_txn.debit || 0), fmt(p.ledger_txn.credit || 0), p.ledger_txn.balance != null ? fmt(p.ledger_txn.balance) : "", `${Math.round(p.confidence * 100)}%`, p.reason || `Smart ${i + 1}`]]);
      return [header, ...exact, ...smart];
    }
    if (activeView === "statement_only") return [header, ...result.statement_only.map(txn => ["Bank statement only", "Bank statement", txn.date, txn.description, fmt(txn.amount), fmt(txn.debit || 0), fmt(txn.credit || 0), txn.balance != null ? fmt(txn.balance) : "", "", isAr ? "تحتاج تسجيل قيد محاسبي مقترح" : "Needs suggested journal entry"] )];
    if (activeView === "ledger_only") return [header, ...result.ledger_only.map(txn => ["Books only", "Accounting books", txn.date, txn.description, fmt(txn.amount), fmt(txn.debit || 0), fmt(txn.credit || 0), txn.balance != null ? fmt(txn.balance) : "", "", isAr ? "تحتاج مراجعة مقابل كشف البنك" : "Needs review against bank statement"] )];
    return [["Metric", "Value"], ["Bank statement total", fmt(result.statement_total)], ["Accounting books total", fmt(result.ledger_total)], ["Difference", fmt(result.difference)], ["Matched count", String(matchedCount)], ["Bank statement only count", String(result.statement_only.length)], ["Books only count", String(result.ledger_only.length)]];
  };

  const exportCurrent = () => { downloadCSV(`reconciliation_${activeView}_${new Date().toISOString().slice(0, 10)}.csv`, buildRows()); setNotice(isAr ? "تم تجهيز ملف CSV للمعالجة." : "CSV exported for processing."); };
  const copyCurrent = async () => { if (!navigator.clipboard) return; await navigator.clipboard.writeText(buildRows().map(row => row.join("\t")).join("\n")); setNotice(isAr ? "تم نسخ التفاصيل." : "Details copied."); };
  const markProcessed = () => { setProcessedViews(prev => ({ ...prev, [activeView]: true })); setNotice(isAr ? "تم تحديد هذه المجموعة كمراجعة/معالجة داخل التقرير." : "This group was marked reviewed/processed in the report."); };
  const actionLabel = () => activeView === "matched" ? (isAr ? "اعتماد المتطابق" : "Approve matches") : activeView === "statement_only" ? (isAr ? "تحديد كجاهزة للتسجيل" : "Mark ready to record") : activeView === "ledger_only" ? (isAr ? "تحديد كجاهزة للمراجعة" : "Mark ready for review") : (isAr ? "تحديد الفرق كمراجع" : "Mark difference reviewed");
  const current = meta[activeView];

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {(Object.keys(meta) as ResultView[]).map(view => {
          const item = meta[view];
          const active = activeView === view;
          return <button key={view} onClick={() => { setActiveView(view); setNotice(""); }} className={`wood-card !p-3 text-start border transition-all hover:-translate-y-0.5 hover:bg-white/5 ${item.border} ${active ? "ring-2 ring-amber-400/70 bg-white/5" : ""}`}><div className="flex items-center justify-between gap-2"><span className="text-2xl">{item.icon}</span>{processedViews[view] && <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[9px] text-emerald-300">{isAr ? "تمت المراجعة" : "Reviewed"}</span>}</div><p className="mt-2 text-[10px] text-white/50">{item.title}</p><p className={`text-2xl font-bold tabular-nums ${item.text}`}>{item.count}</p><p className="mt-1 text-[9px] text-white/40 leading-relaxed">{item.hint}</p></button>;
        })}
      </div>

      <div className={`rounded-xl border p-3 ${isBalanced ? "border-emerald-500/30 bg-emerald-500/10" : "border-amber-500/30 bg-amber-500/10"}`}><p className="font-bold text-sm text-white">{isBalanced ? (isAr ? "✅ نتيجة المطابقة: لا يوجد فرق" : "✅ No difference") : (isAr ? "⚠️ نتيجة المطابقة: يوجد فرق يحتاج مراجعة" : "⚠️ Review needed")}</p><p className="text-[11px] text-white/60 mt-1">{isAr ? "اضغط على أي بطاقة أعلاه لفتح تفاصيلها ومعالجتها." : "Click any card above to open its detail panel and processing actions."}</p></div>

      <div className={`rounded-2xl border ${current.border} bg-black/25 overflow-hidden`}>
        <div className="p-3 border-b border-white/10 flex flex-col md:flex-row md:items-center md:justify-between gap-3"><div><h4 className={`text-base font-bold ${current.text}`}>{current.icon} {current.title}</h4><p className="text-[10px] text-white/50 mt-1">{activeView === "matched" && (isAr ? "هذه العمليات تمت مطابقتها بين كشف البنك والدفاتر. الإجراء المطلوب: اعتمادها وحفظ التقرير." : "Matched between bank statement and books. Required action: approve and keep report.")}{activeView === "statement_only" && (isAr ? "هذه العمليات موجودة في كشف البنك فقط. الإجراء المطلوب: إنشاء قيد مقترح ثم اعتماده قبل التسجيل." : "Rows exist only in bank statement. Required action: create and approve suggested entries.")}{activeView === "ledger_only" && (isAr ? "هذه العمليات موجودة في الدفاتر فقط. الإجراء المطلوب: مراجعة السند أو التاريخ أو المبلغ مقابل كشف البنك." : "Rows exist only in books. Required action: review support/date/amount against bank statement.")}{activeView === "difference" && (isAr ? "هذا تحليل الفرق النهائي بين كشف البنك والدفاتر." : "Final difference analysis between bank statement and books.")}</p></div><div className="flex flex-wrap gap-2">{activeView === "statement_only" && <button onClick={() => setShowJournalDrafts(prev => !prev)} className="px-3 py-1.5 rounded-lg bg-cyan-500/15 border border-cyan-500/40 text-cyan-300 text-xs font-bold">🧾 {isAr ? "تسجيل العمليات في الحسابات" : "Prepare journal entries"}</button>}<button onClick={markProcessed} className="px-3 py-1.5 rounded-lg bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 text-xs font-bold">✅ {actionLabel()}</button><button onClick={exportCurrent} className="px-3 py-1.5 rounded-lg bg-blue-500/15 border border-blue-500/40 text-blue-300 text-xs font-bold">📊 {isAr ? "تصدير للمعالجة" : "Export"}</button><button onClick={copyCurrent} className="px-3 py-1.5 rounded-lg bg-purple-500/15 border border-purple-500/40 text-purple-300 text-xs font-bold">📋 {isAr ? "نسخ التفاصيل" : "Copy"}</button><button onClick={() => window.print()} className="px-3 py-1.5 rounded-lg bg-rose-500/15 border border-rose-500/40 text-rose-300 text-xs font-bold">🖨️ {isAr ? "طباعة" : "Print"}</button></div></div>
        {notice && <div className="mx-3 mt-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-2 text-[11px] text-emerald-300">{notice}</div>}
        <div className="p-3 space-y-3 max-h-[520px] overflow-auto">
          {activeView === "matched" && <div className="space-y-3">{result.matched.length === 0 && result.smart_matched.length === 0 && <p className="text-white/40">{isAr ? "لا توجد عمليات متطابقة." : "No matched transactions."}</p>}{result.matched.map((pair, idx) => <div key={`m-${idx}`} className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3"><div className="mb-2 flex items-center justify-between gap-2"><span className="font-bold text-emerald-300">✅ {isAr ? "مطابقة مباشرة" : "Exact match"} #{idx + 1}</span><span className="font-mono text-emerald-300">100%</span></div><div className="grid md:grid-cols-2 gap-2"><TxnCard txn={pair.statement_txn} label={isAr ? "كشف البنك" : "Bank statement"} isAr={isAr} /><TxnCard txn={pair.ledger_txn} label={isAr ? "الدفاتر" : "Books"} isAr={isAr} /></div></div>)}{result.smart_matched.map((pair, idx) => <div key={`s-${idx}`} className="rounded-xl border border-purple-500/20 bg-purple-500/5 p-3"><div className="mb-2 flex items-center justify-between gap-2"><span className="font-bold text-purple-300">🧠 {isAr ? "مطابقة دلالية" : "Semantic match"} #{idx + 1}</span><span className="font-mono text-purple-300">{Math.round(pair.confidence * 100)}%</span></div><div className="grid md:grid-cols-2 gap-2"><TxnCard txn={pair.statement_txn} label={isAr ? "كشف البنك" : "Bank statement"} isAr={isAr} /><TxnCard txn={pair.ledger_txn} label={isAr ? "الدفاتر" : "Books"} isAr={isAr} /></div>{pair.reason && <p className="mt-2 text-[10px] text-white/50">{pair.reason}</p>}</div>)}</div>}
          {activeView === "statement_only" && <div className="space-y-3">{result.statement_only.length === 0 ? <p className="text-white/40">{isAr ? "لا توجد عمليات مسجلة في كشف البنك فقط." : "No bank-statement-only rows."}</p> : <>{!showJournalDrafts && <div className="space-y-2">{result.statement_only.map((txn, idx) => <TxnCard key={idx} txn={txn} label={isAr ? "كشف البنك فقط" : "Bank statement only"} isAr={isAr} />)}</div>}{showJournalDrafts && <div className="space-y-3"><div className="rounded-xl border border-cyan-500/30 bg-cyan-500/10 p-3 text-[11px] text-white/70"><p className="font-bold text-cyan-300 mb-1">🧠 {isAr ? "اقتراح القيود بطريقة NLP / Semantic Matching" : "Journal suggestions using NLP / Semantic Matching"}</p><p>{isAr ? "إذا كانت العملية إيداعًا يظهر الحساب البنكي المختار مدينًا. وإذا كانت تحويلًا صادرًا أو صرفًا يظهر الحساب البنكي المختار دائنًا. الحساب المقابل مقترح من وصف العملية وبيانات الكشف، ويحتاج اعتمادًا قبل التسجيل." : "Deposits debit the selected bank account. Outgoing transfers/payments credit the selected bank account. Counter account is suggested from transaction description and requires approval before posting."}</p></div>{result.statement_only.map((txn, idx) => <SuggestedEntryCard key={idx} txn={txn} index={idx} isAr={isAr} bankAccountLabel={bankAccountLabel} />)}</div>}</>}</div>}
          {activeView === "ledger_only" && <div className="space-y-2">{result.ledger_only.length === 0 ? <p className="text-white/40">{isAr ? "لا توجد عمليات مسجلة في الدفاتر فقط." : "No books-only rows."}</p> : result.ledger_only.map((txn, idx) => <TxnCard key={idx} txn={txn} label={isAr ? "الدفاتر فقط" : "Books only"} isAr={isAr} />)}</div>}
          {activeView === "difference" && <div className="space-y-3"><div className="grid md:grid-cols-3 gap-2"><div className="rounded-xl border border-white/10 bg-black/20 p-3"><p className="text-[10px] text-white/50">{isAr ? "إجمالي كشف البنك" : "Bank statement total"}</p><p className="text-xl font-bold text-amber-300 font-mono">{fmt(result.statement_total)}</p></div><div className="rounded-xl border border-white/10 bg-black/20 p-3"><p className="text-[10px] text-white/50">{isAr ? "إجمالي الدفاتر" : "Books total"}</p><p className="text-xl font-bold text-blue-300 font-mono">{fmt(result.ledger_total)}</p></div><div className="rounded-xl border border-white/10 bg-black/20 p-3"><p className="text-[10px] text-white/50">{isAr ? "الفرق" : "Difference"}</p><p className={`text-xl font-bold font-mono ${isBalanced ? "text-emerald-300" : "text-rose-300"}`}>{fmt(result.difference)}</p></div></div><div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-3 text-[11px] text-white/70 leading-relaxed"><p className="font-bold text-amber-300 mb-1">{isAr ? "المعالجة المقترحة" : "Suggested processing"}</p><p>{isAr ? "ابدأ بمراجعة العمليات المسجلة في كشف البنك فقط والعمليات المسجلة في الدفاتر فقط. غالبًا الفرق ناتج عن عمليات لم تُسجل، عمليات مكررة، تاريخ خارج الفترة، أو اختلاف في الإشارة مدين/دائن." : "Start by reviewing bank-statement-only and books-only rows. Difference is usually caused by missing entries, duplicates, out-of-period dates, or debit/credit sign differences."}</p></div><div className="grid md:grid-cols-2 gap-3"><div className="space-y-2"><p className="font-bold text-amber-300">📄 {isAr ? "مسجلة في كشف البنك فقط" : "Bank statement only"}</p>{result.statement_only.map((txn, idx) => <TxnCard key={idx} txn={txn} label={isAr ? "كشف البنك" : "Bank statement"} isAr={isAr} />)}</div><div className="space-y-2"><p className="font-bold text-rose-300">📚 {isAr ? "مسجلة في الدفاتر فقط" : "Books only"}</p>{result.ledger_only.map((txn, idx) => <TxnCard key={idx} txn={txn} label={isAr ? "الدفاتر" : "Books"} isAr={isAr} />)}</div></div></div>}
        </div>
      </div>
    </div>
  );
}
