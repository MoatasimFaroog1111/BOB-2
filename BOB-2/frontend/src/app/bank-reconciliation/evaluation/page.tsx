"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { API_BASE_URL } from "@/lib/api";
import { useCompany } from "@/lib/CompanyContext";
import { useLanguage } from "@/lib/LanguageContext";

type BankJournal = {
  journal_id: number;
  journal_name: string;
  journal_code: string;
  account_id?: number | null;
  account_name?: string;
  account_code?: string;
  company_id?: number | null;
  company_name?: string;
};

type MetricPair = {
  accuracy_on_labeled_pct?: number;
  labeled_support?: number;
  coverage_on_labeled?: number;
};

type SplitSummary = {
  examples: number;
  date_from?: string | null;
  date_to?: string | null;
  distinct_dates: number;
};

type TestMetrics = {
  sample_count: number;
  account: {
    top1_accuracy_pct: number;
    top3_accuracy_pct: number;
    coverage_pct: number;
  };
  partner: MetricPair;
  analytic: MetricPair;
  vat_detection: {
    accuracy_pct: number;
    precision: number;
    recall: number;
    f1: number;
    positive_support: number;
    tp: number;
    tn: number;
    fp: number;
    fn: number;
  };
  strict_joint_accuracy_pct: number;
  review_gate: {
    threshold: number;
    accepted_account_precision_pct: number;
    accepted_coverage_pct: number;
    accepted_count: number;
  };
  error_samples?: Array<{
    move_id: number;
    date: string;
    target_account_id: number;
    predicted_account_id?: number | null;
    confidence: number;
  }>;
};

type EvaluationReport = {
  status: string;
  method: string;
  dataset: {
    historical_entries_read: number;
    labeled_cases: number;
    date_from?: string | null;
    date_to?: string | null;
  };
  split: {
    train: SplitSummary;
    validation: SplitSummary;
    test: SplitSummary;
  };
  leakage_checks: {
    move_id_overlap: Record<string, number>;
    accounting_date_overlap: Record<string, number>;
    strictly_chronological_boundaries: boolean;
    post_generated_move_name_removed_from_query: boolean;
    validation_used_for_threshold_calibration: boolean;
    test_used_for_threshold_calibration: boolean;
    test_rows_added_to_test_history_corpus: boolean;
  };
  calibration: {
    threshold: number;
    precision: number;
    coverage: number;
    accepted: number;
    policy: string;
    target_precision?: number;
  };
  untouched_test_metrics: TestMetrics;
  accuracy_summary_pct: {
    account_top1: number;
    account_top3: number;
    partner_on_labeled: number;
    vat_detection: number;
    analytic_on_labeled: number;
    strict_joint: number;
  };
  safe_to_post: boolean;
  erp_mutation: boolean;
};

function pct(value: number | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value.toFixed(2)}%`;
}

function ratioPct(value: number | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(2)}%`;
}

function metricTone(value: number | undefined): string {
  if (value == null) return "text-gray-300";
  if (value >= 95) return "text-emerald-300";
  if (value >= 90) return "text-lime-300";
  if (value >= 80) return "text-amber-300";
  return "text-rose-300";
}

export default function BankReconciliationEvaluationPage() {
  const { language } = useLanguage();
  const { selectedCompanyId } = useCompany();
  const isAr = language === "ar";
  const msg = useCallback((ar: string, en: string) => (isAr ? ar : en), [isAr]);

  const [journals, setJournals] = useState<BankJournal[]>([]);
  const [selectedJournalId, setSelectedJournalId] = useState("");
  const [historyLimit, setHistoryLimit] = useState("1500");
  const [journalsLoading, setJournalsLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState<EvaluationReport | null>(null);

  useEffect(() => {
    let alive = true;
    async function loadJournals() {
      setJournalsLoading(true);
      setError("");
      setReport(null);
      try {
        const query = selectedCompanyId ? `?company_id=${selectedCompanyId}` : "";
        const response = await fetch(`${API_BASE_URL}/api/v1/erp/bank-journals${query}`, { cache: "no-store" });
        const body = await response.json().catch(() => null);
        if (!response.ok) throw new Error(body?.detail || `Error ${response.status}`);
        const items = Array.isArray(body?.items) ? (body.items as BankJournal[]) : [];
        if (!alive) return;
        setJournals(items);
        setSelectedJournalId(items.length === 1 ? String(items[0].journal_id) : "");
      } catch (loadError) {
        if (!alive) return;
        setJournals([]);
        setSelectedJournalId("");
        setError(loadError instanceof Error ? loadError.message : String(loadError));
      } finally {
        if (alive) setJournalsLoading(false);
      }
    }
    loadJournals();
    return () => { alive = false; };
  }, [selectedCompanyId]);

  const selectedJournal = useMemo(
    () => journals.find((journal) => String(journal.journal_id) === selectedJournalId) || null,
    [journals, selectedJournalId],
  );

  const runEvaluation = async () => {
    if (!selectedJournalId) return;
    setRunning(true);
    setError("");
    setReport(null);
    try {
      const params = new URLSearchParams();
      if (selectedCompanyId) params.set("company_id", String(selectedCompanyId));
      params.set("bank_journal_id", selectedJournalId);
      if (selectedJournal?.account_id) params.set("bank_account_id", String(selectedJournal.account_id));
      params.set("history_limit", historyLimit);

      const response = await fetch(
        `${API_BASE_URL}/api/v1/erp/bank-reconciliation/evaluation?${params.toString()}`,
        { cache: "no-store" },
      );
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail || `Error ${response.status}`);
      setReport(body as EvaluationReport);
    } catch (evaluationError) {
      setError(evaluationError instanceof Error ? evaluationError.message : String(evaluationError));
    } finally {
      setRunning(false);
    }
  };

  const metrics = report?.untouched_test_metrics;

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-6" dir={isAr ? "rtl" : "ltr"}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-2 flex items-center gap-2 text-xs text-cyan-200/70">
            <Link href="/bank-reconciliation" className="hover:text-cyan-100">{msg("المطابقة البنكية", "Bank Reconciliation")}</Link>
            <span>/</span>
            <span>{msg("اختبار الدقة الحقيقي", "Live Accuracy Test")}</span>
          </div>
          <h1 className="text-2xl font-bold text-white">{msg("اختبار الدقة الحقيقي على تاريخ Odoo", "Live Accuracy Test on Odoo History")}</h1>
          <p className="mt-1 max-w-3xl text-sm text-gray-400">
            {msg(
              "اختبار زمني مغلق يستخدم أحدث جزء من القيود البنكية المرحّلة كـ Untouched Test، ويقفل حد الثقة قبل الاختبار لمنع تسريب البيانات.",
              "A locked chronological evaluation that uses the latest posted bank history as an untouched test set and freezes the confidence threshold before testing to prevent leakage.",
            )}
          </p>
        </div>
        <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs font-semibold text-emerald-300">{msg("قراءة فقط — لا ترحيل", "Read only — no posting")}</span>
      </div>

      <section className="rounded-2xl border border-white/10 bg-black/30 p-5 space-y-4">
        <div className="grid gap-4 lg:grid-cols-[2fr_1fr_auto] lg:items-end">
          <div>
            <label className="mb-1 block text-xs text-gray-400">{msg("دفتر البنك المراد تقييمه", "Bank journal to evaluate")}</label>
            <select
              value={selectedJournalId}
              onChange={(event) => setSelectedJournalId(event.target.value)}
              disabled={journalsLoading || running || journals.length === 0}
              className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/50 disabled:opacity-50"
            >
              <option value="">{journalsLoading ? msg("جاري تحميل دفاتر البنك...", "Loading bank journals...") : msg("اختر دفتر البنك", "Select bank journal")}</option>
              {journals.map((journal) => (
                <option key={journal.journal_id} value={journal.journal_id}>
                  {journal.journal_name} ({journal.journal_code}) — {journal.account_code || "—"}{journal.company_name ? ` — ${journal.company_name}` : ""}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="mb-1 block text-xs text-gray-400">{msg("حجم التاريخ المقروء", "History read limit")}</label>
            <select
              value={historyLimit}
              onChange={(event) => setHistoryLimit(event.target.value)}
              disabled={running}
              className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/50 disabled:opacity-50"
            >
              <option value="600">600</option>
              <option value="1000">1000</option>
              <option value="1500">1500</option>
            </select>
          </div>

          <button
            type="button"
            disabled={!selectedJournalId || running}
            onClick={runEvaluation}
            className="rounded-xl bg-gradient-to-r from-cyan-400 to-emerald-400 px-5 py-2.5 text-sm font-bold text-slate-950 transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
          >
            {running ? msg("جاري تشغيل Untouched Test...", "Running untouched test...") : msg("تشغيل الاختبار الحقيقي", "Run live accuracy test")}
          </button>
        </div>

        {selectedJournal && (
          <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 px-4 py-3 text-xs text-cyan-100/80">
            {msg("النطاق", "Scope")}: {selectedJournal.journal_name} ({selectedJournal.journal_code}) · {selectedJournal.account_code || "—"} {selectedJournal.account_name || ""}
          </div>
        )}
        {error && <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">{error}</div>}
      </section>

      {report && metrics && (
        <>
          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            {[
              [msg("الحساب Top-1", "Account Top-1"), report.accuracy_summary_pct.account_top1],
              [msg("الحساب Top-3", "Account Top-3"), report.accuracy_summary_pct.account_top3],
              [msg("الشريك", "Partner"), report.accuracy_summary_pct.partner_on_labeled],
              [msg("ضريبة VAT", "VAT"), report.accuracy_summary_pct.vat_detection],
              [msg("التحليلي", "Analytic"), report.accuracy_summary_pct.analytic_on_labeled],
              [msg("الدقة المشتركة", "Joint"), report.accuracy_summary_pct.strict_joint],
            ].map(([label, value]) => (
              <div key={String(label)} className="rounded-xl border border-white/10 bg-black/30 p-4">
                <p className="text-[11px] uppercase tracking-wide text-gray-500">{label}</p>
                <p className={`mt-2 text-2xl font-black ${metricTone(Number(value))}`}>{pct(Number(value))}</p>
              </div>
            ))}
          </section>

          <section className="grid gap-4 xl:grid-cols-[1.25fr_1fr]">
            <div className="rounded-2xl border border-white/10 bg-black/30 p-5">
              <h2 className="text-base font-semibold text-white">{msg("تفاصيل Untouched Test", "Untouched Test Details")}</h2>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <Detail label={msg("عدد حالات الاختبار", "Test cases")} value={String(metrics.sample_count)} />
                <Detail label={msg("تغطية الحساب", "Account coverage")} value={pct(metrics.account.coverage_pct)} />
                <Detail label={msg("دقة الحساب المقبولة", "Accepted account precision")} value={pct(metrics.review_gate.accepted_account_precision_pct)} />
                <Detail label={msg("تغطية بوابة الثقة", "Review-gate coverage")} value={pct(metrics.review_gate.accepted_coverage_pct)} />
                <Detail label={msg("حد الثقة المقفول", "Locked confidence threshold")} value={ratioPct(metrics.review_gate.threshold)} />
                <Detail label={msg("عدد المقبول آلياً", "Accepted count")} value={String(metrics.review_gate.accepted_count)} />
                <Detail label="Partner labeled support" value={String(metrics.partner.labeled_support ?? 0)} />
                <Detail label="Partner coverage" value={ratioPct(metrics.partner.coverage_on_labeled)} />
                <Detail label="Analytic labeled support" value={String(metrics.analytic.labeled_support ?? 0)} />
                <Detail label="Analytic coverage" value={ratioPct(metrics.analytic.coverage_on_labeled)} />
                <Detail label="VAT Precision" value={ratioPct(metrics.vat_detection.precision)} />
                <Detail label="VAT Recall" value={ratioPct(metrics.vat_detection.recall)} />
                <Detail label="VAT F1" value={ratioPct(metrics.vat_detection.f1)} />
                <Detail label={msg("VAT حالات موجبة", "VAT positive support")} value={String(metrics.vat_detection.positive_support)} />
              </div>
            </div>

            <div className="rounded-2xl border border-white/10 bg-black/30 p-5">
              <h2 className="text-base font-semibold text-white">{msg("تقسيم البيانات الزمني", "Chronological Data Split")}</h2>
              <div className="mt-4 space-y-3">
                <SplitRow label="Train" value={report.split.train} />
                <SplitRow label="Validation" value={report.split.validation} />
                <SplitRow label="Untouched Test" value={report.split.test} />
              </div>
              <div className="mt-4 border-t border-white/10 pt-4 text-xs text-gray-400">
                {msg("إجمالي التاريخ المقروء", "Historical entries read")}: <span className="text-white">{report.dataset.historical_entries_read}</span><br />
                {msg("الحالات المصنفة الصالحة", "Valid labeled cases")}: <span className="text-white">{report.dataset.labeled_cases}</span><br />
                {msg("الفترة", "Period")}: <span className="text-white">{report.dataset.date_from || "—"} → {report.dataset.date_to || "—"}</span>
              </div>
            </div>
          </section>

          <section className="grid gap-4 xl:grid-cols-2">
            <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-5">
              <h2 className="text-base font-semibold text-emerald-200">{msg("فحوص منع تسريب البيانات", "Anti-Leakage Checks")}</h2>
              <div className="mt-4 grid gap-2 text-sm">
                <Check label={msg("الحدود الزمنية متسلسلة", "Strict chronological boundaries")} ok={report.leakage_checks.strictly_chronological_boundaries} />
                <Check label={msg("إزالة رقم القيد المتولد بعد الترحيل", "Post-generated move name removed")} ok={report.leakage_checks.post_generated_move_name_removed_from_query} />
                <Check label={msg("Validation فقط لمعايرة الثقة", "Validation only calibrates confidence")} ok={report.leakage_checks.validation_used_for_threshold_calibration && !report.leakage_checks.test_used_for_threshold_calibration} />
                <Check label={msg("Test لا يدخل في تاريخ Test", "Test rows excluded from test history")} ok={!report.leakage_checks.test_rows_added_to_test_history_corpus} />
                <Check label={msg("لا تداخل Move IDs بين Train/Test", "No Train/Test move-ID overlap")} ok={(report.leakage_checks.move_id_overlap.train_test ?? 0) === 0} />
                <Check label={msg("لا تداخل تواريخ بين Validation/Test", "No Validation/Test date overlap")} ok={(report.leakage_checks.accounting_date_overlap.validation_test ?? 0) === 0} />
              </div>
            </div>

            <div className="rounded-2xl border border-white/10 bg-black/30 p-5">
              <h2 className="text-base font-semibold text-white">{msg("معايرة بوابة الثقة", "Confidence-Gate Calibration")}</h2>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <Detail label="Threshold" value={ratioPct(report.calibration.threshold)} />
                <Detail label="Validation precision" value={ratioPct(report.calibration.precision)} />
                <Detail label="Validation coverage" value={ratioPct(report.calibration.coverage)} />
                <Detail label="Validation accepted" value={String(report.calibration.accepted)} />
              </div>
              <p className="mt-4 break-words text-xs text-gray-500">{report.calibration.policy}</p>
              <div className="mt-4 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-xs text-gray-300">
                safe_to_post = <span className={report.safe_to_post ? "text-rose-300" : "text-emerald-300"}>{String(report.safe_to_post)}</span> · erp_mutation = <span className={report.erp_mutation ? "text-rose-300" : "text-emerald-300"}>{String(report.erp_mutation)}</span>
              </div>
            </div>
          </section>

          {!!metrics.error_samples?.length && (
            <section className="rounded-2xl border border-rose-500/20 bg-rose-500/5 p-5">
              <h2 className="text-base font-semibold text-rose-200">{msg("عينة أخطاء الحساب", "Account Error Samples")}</h2>
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="border-b border-white/10 text-xs uppercase text-gray-500"><th className="px-3 py-2 text-start">Move</th><th className="px-3 py-2 text-start">{msg("التاريخ", "Date")}</th><th className="px-3 py-2 text-start">{msg("الحساب الصحيح", "Target account")}</th><th className="px-3 py-2 text-start">{msg("المتوقع", "Predicted")}</th><th className="px-3 py-2 text-start">{msg("الثقة", "Confidence")}</th></tr></thead>
                  <tbody>
                    {metrics.error_samples.map((sample) => (
                      <tr key={`${sample.move_id}-${sample.date}`} className="border-b border-white/5 text-gray-300">
                        <td className="px-3 py-2">{sample.move_id}</td><td className="px-3 py-2">{sample.date}</td><td className="px-3 py-2">{sample.target_account_id}</td><td className="px-3 py-2">{sample.predicted_account_id ?? "—"}</td><td className="px-3 py-2">{ratioPct(sample.confidence)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-3"><p className="text-[11px] text-gray-500">{label}</p><p className="mt-1 text-base font-bold text-white">{value}</p></div>;
}

function SplitRow({ label, value }: { label: string; value: SplitSummary }) {
  return <div className="rounded-xl border border-white/10 bg-white/5 px-4 py-3"><div className="flex items-center justify-between gap-3"><span className="font-semibold text-white">{label}</span><span className="text-sm font-bold text-cyan-300">{value.examples}</span></div><p className="mt-1 text-xs text-gray-500">{value.date_from || "—"} → {value.date_to || "—"} · {value.distinct_dates} dates</p></div>;
}

function Check({ label, ok }: { label: string; ok: boolean }) {
  return <div className="flex items-center justify-between gap-4 rounded-lg border border-white/10 bg-black/20 px-3 py-2"><span className="text-gray-300">{label}</span><span className={ok ? "text-emerald-300" : "text-rose-300"}>{ok ? "PASS" : "FAIL"}</span></div>;
}
