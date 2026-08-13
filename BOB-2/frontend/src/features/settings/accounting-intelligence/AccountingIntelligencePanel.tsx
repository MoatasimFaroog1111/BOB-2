"use client";

import { useEffect, useState } from "react";

import {
  fetchAccountingIntelligenceStatus,
  syncAccountingLearning,
  type AccountingIntelligenceStatus,
  type AccountingLearningSyncResult,
} from "@/features/settings/accounting-intelligence/api";
import { useLanguage } from "@/lib/LanguageContext";

function selectedCompanyId(): number | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem("selectedCompanyId");
  const parsed = raw ? Number.parseInt(raw, 10) : NaN;
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

export function AccountingIntelligencePanel() {
  const { language } = useLanguage();
  const ar = language === "ar";
  const [status, setStatus] = useState<AccountingIntelligenceStatus | null>(null);
  const [lastSync, setLastSync] = useState<AccountingLearningSyncResult | null>(null);
  const [limit, setLimit] = useState(1000);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [includeAttachmentContent, setIncludeAttachmentContent] = useState(true);
  const [attachmentContentLimit, setAttachmentContentLimit] = useState(100);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadStatus = async () => {
    try {
      setStatus(await fetchAccountingIntelligenceStatus());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    void loadStatus();
  }, []);

  const runSync = async () => {
    setLoading(true);
    setError("");
    try {
      const result = await syncAccountingLearning({
        date_from: dateFrom || null,
        date_to: dateTo || null,
        limit,
        company_id: selectedCompanyId(),
        include_attachment_content: includeAttachmentContent,
        attachment_content_limit: attachmentContentLimit,
      });
      setLastSync(result);
      await loadStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="space-y-6" dir={ar ? "rtl" : "ltr"}>
      <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-3xl space-y-2">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-300">
              ACCOUNTING INTELLIGENCE
            </div>
            <h1 className="text-2xl font-semibold text-white">
              {ar ? "ذاكرة المحاسب والمدقق الذكي" : "Accountant & Auditor Learning Memory"}
            </h1>
            <p className="text-sm leading-6 text-white/60">
              {ar
                ? "يبني طبقة تعلم من القيود المحاسبية المرحّلة فعليًا في النظام المرتبط، ويستخدم شجرة الحسابات والدفاتر والشركاء والضرائب والتحليلي ومحتوى المرفقات الآمن كمرجع وخصائص. لا ينشئ أو يرحّل أي قيد تلقائيًا."
                : "Builds a learning layer from posted accounting history in the connected ERP and uses accounts, journals, partners, taxes, analytics, and safely extracted attachment content as references/features. It never auto-posts entries."}
            </p>
          </div>
          <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
            {ar ? "وضع آمن: قراءة وتعلّم فقط" : "Safe mode: read & learn only"}
          </div>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Metric
          label={ar ? "أمثلة التعلّم" : "Learning examples"}
          value={status ? status.learning_examples.toLocaleString() : "—"}
        />
        <Metric
          label={ar ? "آخر تعلّم" : "Last learned"}
          value={status?.latest_learning_example_at ? new Date(status.latest_learning_example_at).toLocaleString() : "—"}
        />
        <Metric
          label={ar ? "الترحيل التلقائي" : "Auto posting"}
          value={status?.auto_posting ? (ar ? "مفعل" : "Enabled") : ar ? "مغلق" : "Disabled"}
        />
      </div>

      <div className="rounded-2xl border border-white/10 bg-black/20 p-6">
        <h2 className="mb-4 text-lg font-semibold text-white">
          {ar ? "مزامنة وتعلّم من التاريخ المحاسبي" : "Sync & learn from accounting history"}
        </h2>
        <div className="grid gap-4 md:grid-cols-3">
          <label className="space-y-2 text-sm text-white/70">
            <span>{ar ? "من تاريخ" : "From date"}</span>
            <input
              type="date"
              value={dateFrom}
              onChange={(event) => setDateFrom(event.target.value)}
              className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-white outline-none focus:border-amber-400/50"
            />
          </label>
          <label className="space-y-2 text-sm text-white/70">
            <span>{ar ? "إلى تاريخ" : "To date"}</span>
            <input
              type="date"
              value={dateTo}
              onChange={(event) => setDateTo(event.target.value)}
              className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-white outline-none focus:border-amber-400/50"
            />
          </label>
          <label className="space-y-2 text-sm text-white/70">
            <span>{ar ? "الحد الأقصى للقيود" : "Maximum entries"}</span>
            <input
              type="number"
              min={1}
              max={5000}
              value={limit}
              onChange={(event) => setLimit(Math.min(5000, Math.max(1, Number(event.target.value) || 1)))}
              className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-white outline-none focus:border-amber-400/50"
            />
          </label>
        </div>

        <div className="mt-4 grid gap-4 rounded-xl border border-white/10 bg-white/[0.02] p-4 md:grid-cols-[1fr_220px] md:items-end">
          <label className="flex cursor-pointer items-start gap-3 text-sm text-white/70">
            <input
              type="checkbox"
              checked={includeAttachmentContent}
              onChange={(event) => setIncludeAttachmentContent(event.target.checked)}
              className="mt-1 h-4 w-4 accent-amber-400"
            />
            <span>
              <span className="block font-medium text-white/85">
                {ar ? "التعلّم من محتوى مرفقات النظام المحاسبي" : "Learn from ERP attachment content"}
              </span>
              <span className="mt-1 block text-xs leading-5 text-white/45">
                {ar
                  ? "يقرأ عددًا محدودًا من PDF/الصور/النصوص، ويمررها أولًا عبر حدود الحجم وفحص البرمجيات الخبيثة والتحقق من نوع المحتوى ثم OCR الحالي."
                  : "Reads a bounded set of PDFs/images/text files only after size limits, malware scanning, content/type validation, then the existing OCR pipeline."}
              </span>
            </span>
          </label>
          <label className="space-y-2 text-sm text-white/70">
            <span>{ar ? "حد المرفقات في الدفعة" : "Attachment batch limit"}</span>
            <input
              type="number"
              min={1}
              max={500}
              disabled={!includeAttachmentContent}
              value={attachmentContentLimit}
              onChange={(event) => setAttachmentContentLimit(Math.min(500, Math.max(1, Number(event.target.value) || 1)))}
              className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-white outline-none focus:border-amber-400/50 disabled:opacity-40"
            />
          </label>
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={loading}
            onClick={() => void runSync()}
            className="rounded-xl bg-amber-400 px-5 py-2.5 text-sm font-semibold text-black transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading
              ? ar
                ? "جاري التعلّم..."
                : "Learning..."
              : ar
                ? "مزامنة وتعلّم الآن"
                : "Sync & Learn Now"}
          </button>
          <span className="text-xs text-white/45">
            {ar
              ? "القيود المرحّلة هي Outputs/Labels؛ المرفقات والبيانات السابقة للترحيل هي Features."
              : "Posted entries are Outputs/Labels; attachments and pre-posting evidence are Features."}
          </span>
        </div>
      </div>

      {error ? (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">{error}</div>
      ) : null}

      {lastSync ? (
        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-6">
          <h2 className="mb-4 text-lg font-semibold text-white">{ar ? "نتيجة آخر مزامنة" : "Latest sync result"}</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Metric label={ar ? "تمت قراءتها" : "Read"} value={String(lastSync.examples_read)} compact />
            <Metric label={ar ? "جديدة" : "Created"} value={String(lastSync.created)} compact />
            <Metric label={ar ? "محدثة" : "Updated"} value={String(lastSync.updated)} compact />
            <Metric label={ar ? "بدون تغيير" : "Unchanged"} value={String(lastSync.unchanged)} compact />
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <Metric label={ar ? "مرفقات مطلوبة" : "Attachments requested"} value={String(lastSync.attachment_content_learning.requested)} compact />
            <Metric label={ar ? "تم استخراجها" : "Text extracted"} value={String(lastSync.attachment_content_learning.extracted)} compact />
            <Metric label={ar ? "مرفوضة أمنيًا" : "Rejected"} value={String(lastSync.attachment_content_learning.rejected)} compact />
            <Metric label={ar ? "تم تجاوزها" : "Skipped"} value={String(lastSync.attachment_content_learning.skipped)} compact />
            <Metric label={ar ? "فشل استخراجها" : "Failed"} value={String(lastSync.attachment_content_learning.failed)} compact />
          </div>
          <div className="mt-4 rounded-xl border border-white/10 bg-black/20 p-4 text-xs leading-6 text-white/55">
            {ar
              ? `الحسابات: ${lastSync.reference_catalog.accounts ?? 0} • الدفاتر: ${lastSync.reference_catalog.journals ?? 0} • الشركاء: ${lastSync.reference_catalog.partners ?? 0} • الضرائب: ${lastSync.reference_catalog.taxes ?? 0} • التحليلي: ${lastSync.reference_catalog.analytic_accounts ?? 0}`
              : `Accounts: ${lastSync.reference_catalog.accounts ?? 0} • Journals: ${lastSync.reference_catalog.journals ?? 0} • Partners: ${lastSync.reference_catalog.partners ?? 0} • Taxes: ${lastSync.reference_catalog.taxes ?? 0} • Analytics: ${lastSync.reference_catalog.analytic_accounts ?? 0}`}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function Metric({ label, value, compact = false }: { label: string; value: string; compact?: boolean }) {
  return (
    <div className={`rounded-xl border border-white/10 bg-black/20 ${compact ? "p-4" : "p-5"}`}>
      <div className="text-xs text-white/45">{label}</div>
      <div className={`${compact ? "mt-1 text-lg" : "mt-2 text-xl"} font-semibold text-white`}>{value}</div>
    </div>
  );
}
