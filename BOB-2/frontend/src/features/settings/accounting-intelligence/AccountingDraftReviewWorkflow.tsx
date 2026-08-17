"use client";

import { useMemo, useState } from "react";

import {
  analyzeAccountingDocument,
  createReviewedAccountingDraft,
  type AccountingCandidate,
  type AccountingDocumentReviewResult,
  type ReviewedDraftResult,
} from "@/features/settings/accounting-intelligence/api";
import { useLanguage } from "@/lib/LanguageContext";

function selectedCompanyId(): number | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem("selectedCompanyId");
  const parsed = raw ? Number.parseInt(raw, 10) : NaN;
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

function candidateLabel(candidate: AccountingCandidate) {
  const code = candidate.code || candidate.label || "";
  const name = candidate.name || "";
  const score = candidate.model_score ?? candidate.confidence;
  const suffix = typeof score === "number" ? ` · ${(score * 100).toFixed(1)}%` : "";
  return `${code}${code && name ? " — " : ""}${name}${suffix}` || String(candidate.id || "");
}

function optionCandidates(rows: AccountingCandidate[]) {
  return rows.filter((row) => row.id && row.live_reference_resolved !== false);
}

export function AccountingDraftReviewWorkflow() {
  const { language } = useLanguage();
  const ar = language === "ar";
  const [file, setFile] = useState<File | null>(null);
  const [analysis, setAnalysis] = useState<AccountingDocumentReviewResult | null>(null);
  const [result, setResult] = useState<ReviewedDraftResult | null>(null);
  const [amount, setAmount] = useState("");
  const [entryDate, setEntryDate] = useState("");
  const [description, setDescription] = useState("");
  const [journalId, setJournalId] = useState<number | null>(null);
  const [debitAccountId, setDebitAccountId] = useState<number | null>(null);
  const [creditAccountId, setCreditAccountId] = useState<number | null>(null);
  const [debitPartnerId, setDebitPartnerId] = useState<number | null>(null);
  const [creditPartnerId, setCreditPartnerId] = useState<number | null>(null);
  const [debitAnalyticId, setDebitAnalyticId] = useState<number | null>(null);
  const [creditAnalyticId, setCreditAnalyticId] = useState<number | null>(null);
  const [approved, setApproved] = useState(false);
  const [loading, setLoading] = useState<"analyze" | "create" | null>(null);
  const [error, setError] = useState("");

  const taxReviewRequired = useMemo(
    () => Boolean(analysis?.prediction.taxes.some((row) => row.selected)),
    [analysis],
  );

  const resetReview = () => {
    setAnalysis(null);
    setResult(null);
    setAmount("");
    setEntryDate("");
    setDescription("");
    setJournalId(null);
    setDebitAccountId(null);
    setCreditAccountId(null);
    setDebitPartnerId(null);
    setCreditPartnerId(null);
    setDebitAnalyticId(null);
    setCreditAnalyticId(null);
    setApproved(false);
    setError("");
  };

  const analyze = async () => {
    if (!file) return;
    const companyId = selectedCompanyId();
    if (!companyId) {
      setError(ar ? "اختر الشركة أولًا من النظام." : "Select a company first.");
      return;
    }
    setLoading("analyze");
    setError("");
    setResult(null);
    try {
      const next = await analyzeAccountingDocument(file, companyId, amount || undefined);
      setAnalysis(next);
      setAmount(next.document.detected_amount != null ? String(next.document.detected_amount) : amount);
      setEntryDate(next.document.detected_entry_date || "");
      setDescription(file.name);
      setJournalId(next.review_defaults.journal_id);
      setDebitAccountId(next.review_defaults.debit_account_id);
      setCreditAccountId(next.review_defaults.credit_account_id);
      setDebitPartnerId(next.review_defaults.debit_partner_id);
      setCreditPartnerId(next.review_defaults.credit_partner_id);
      setDebitAnalyticId(next.review_defaults.debit_analytic_id);
      setCreditAnalyticId(next.review_defaults.credit_analytic_id);
      setApproved(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(null);
    }
  };

  const createDraft = async () => {
    const companyId = selectedCompanyId();
    if (!file || !analysis || !companyId || !journalId || !debitAccountId || !creditAccountId) return;
    setLoading("create");
    setError("");
    try {
      const next = await createReviewedAccountingDraft({
        file,
        companyId,
        amount,
        entryDate,
        journalId,
        debitAccountId,
        creditAccountId,
        debitPartnerId,
        creditPartnerId,
        debitAnalyticId,
        creditAnalyticId,
        description,
      });
      setResult(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(null);
    }
  };

  const canCreate = Boolean(
    analysis &&
      file &&
      approved &&
      !taxReviewRequired &&
      Number(amount) > 0 &&
      /^\d{4}-\d{2}-\d{2}$/.test(entryDate) &&
      journalId &&
      debitAccountId &&
      creditAccountId &&
      debitAccountId !== creditAccountId &&
      !loading,
  );

  return (
    <section className="space-y-5 rounded-2xl border border-amber-400/20 bg-amber-400/[0.04] p-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-300">DOCUMENT → REVIEW → ODOO DRAFT</div>
          <h2 className="mt-2 text-xl font-semibold text-white">
            {ar ? "مراجعة المستند واعتماده كمسودة" : "Review document and approve as draft"}
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-white/55">
            {ar
              ? "يرفع المستند إلى V2 للقراءة والتوصية فقط، ثم يظل القرار للمحاسب. عند الاعتماد يعيد الخادم التحليل من نفس الملف، يتحقق من كل ID مباشرة من Odoo، ينشئ Draft فقط ويربط المرفق."
              : "V2 reads and recommends only. On approval the server re-analyzes the same file, validates every selected ID against live Odoo, creates a draft only, and attaches the source document."}
          </p>
        </div>
        <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/10 px-4 py-2 text-xs font-medium text-emerald-200">
          {ar ? "لا يوجد ترحيل تلقائي" : "No auto-posting"}
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-[1fr_auto]">
        <label className="rounded-xl border border-dashed border-white/15 bg-black/20 p-4 text-sm text-white/65">
          <span className="mb-2 block font-medium text-white/85">{ar ? "المستند المحاسبي" : "Accounting source document"}</span>
          <input
            type="file"
            accept=".pdf,.png,.jpg,.jpeg,.webp,.txt,.csv"
            onChange={(event) => {
              setFile(event.target.files?.[0] || null);
              resetReview();
            }}
            className="block w-full text-xs text-white/60 file:me-3 file:rounded-lg file:border-0 file:bg-white/10 file:px-3 file:py-2 file:text-white"
          />
          {file ? <span className="mt-2 block text-xs text-white/40">{file.name} · {(file.size / 1024).toFixed(1)} KB</span> : null}
        </label>
        <button
          type="button"
          disabled={!file || Boolean(loading)}
          onClick={() => void analyze()}
          className="self-stretch rounded-xl bg-amber-400 px-5 py-3 text-sm font-semibold text-black transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {loading === "analyze" ? (ar ? "جاري التحليل..." : "Analyzing...") : ar ? "تحليل للمراجعة" : "Analyze for review"}
        </button>
      </div>

      {error ? <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">{error}</div> : null}

      {analysis ? (
        <div className="space-y-5">
          <div className="grid gap-3 md:grid-cols-4">
            <Info label={ar ? "نوع المستند" : "Document class"} value={analysis.document.document_class} />
            <Info label={ar ? "ثقة النموذج" : "Model confidence"} value={`${((analysis.prediction.confidence_proxy || 0) * 100).toFixed(1)}%`} />
            <Info
              label={ar ? "قرار البوابة" : "Safety gate"}
              value={analysis.decision_gate.draft_eligible ? (ar ? "مؤهل آليًا" : "Auto eligible") : ar ? "مراجعة مطلوبة" : "Review required"}
            />
            <Info label="SHA-256" value={`${analysis.source.sha256.slice(0, 12)}…`} />
          </div>

          {!analysis.decision_gate.draft_eligible ? (
            <div className="rounded-xl border border-amber-400/30 bg-amber-400/10 p-4 text-sm text-amber-100">
              {ar
                ? "البوابة الأصلية ما زالت محجوبة ولم نخفض أي Threshold. هذا المسار يسمح بالإنشاء فقط لأنك ستراجع وتوافق صراحةً على الاختيارات أدناه."
                : "The original gate remains blocked and no threshold is lowered. Creation is allowed only after your explicit review of the selections below."}
            </div>
          ) : null}

          {taxReviewRequired ? (
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">
              {ar
                ? "النموذج اختار ضريبة لهذا المستند. تم تعطيل زر إنشاء المسودة حتى يمر المستند بمسار مراجعة الضرائب المخصص؛ لن يتم إسقاط الضريبة بصمت."
                : "The model selected tax. Draft creation is disabled until the dedicated tax-review workflow handles it; tax will never be silently omitted."}
            </div>
          ) : null}

          <div className="grid gap-4 md:grid-cols-2">
            <TextField label={ar ? "المبلغ" : "Amount"} type="number" value={amount} onChange={setAmount} />
            <TextField label={ar ? "تاريخ القيد" : "Entry date"} type="date" value={entryDate} onChange={setEntryDate} />
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <CandidateSelect label={ar ? "الدفتر" : "Journal"} rows={analysis.prediction.journals} value={journalId} onChange={setJournalId} />
            <CandidateSelect label={ar ? "الحساب المدين" : "Debit account"} rows={analysis.prediction.debit_accounts} value={debitAccountId} onChange={setDebitAccountId} />
            <CandidateSelect label={ar ? "الحساب الدائن" : "Credit account"} rows={analysis.prediction.credit_accounts} value={creditAccountId} onChange={setCreditAccountId} />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <CandidateSelect
              label={`${ar ? "شريك السطر المدين" : "Debit-line partner"}${analysis.review_defaults.counterpart_side === "debit" ? " ★" : ""}`}
              rows={analysis.partner_candidates}
              value={debitPartnerId}
              onChange={setDebitPartnerId}
              optional
            />
            <CandidateSelect
              label={`${ar ? "شريك السطر الدائن" : "Credit-line partner"}${analysis.review_defaults.counterpart_side === "credit" ? " ★" : ""}`}
              rows={analysis.partner_candidates}
              value={creditPartnerId}
              onChange={setCreditPartnerId}
              optional
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <CandidateSelect
              label={ar ? "تحليلي السطر المدين (100%)" : "Debit analytic (100%)"}
              rows={analysis.prediction.analytic_accounts}
              value={debitAnalyticId}
              onChange={setDebitAnalyticId}
              optional
            />
            <CandidateSelect
              label={ar ? "تحليلي السطر الدائن (100%)" : "Credit analytic (100%)"}
              rows={analysis.prediction.analytic_accounts}
              value={creditAnalyticId}
              onChange={setCreditAnalyticId}
              optional
            />
          </div>

          <TextField label={ar ? "الوصف" : "Description"} value={description} onChange={setDescription} />

          <details className="rounded-xl border border-white/10 bg-black/20 p-4 text-xs text-white/55">
            <summary className="cursor-pointer font-medium text-white/75">{ar ? "النص المستخرج والتفاصيل" : "Extracted text and details"}</summary>
            <pre className="mt-3 max-h-56 overflow-auto whitespace-pre-wrap leading-5">{analysis.document.text_preview}</pre>
          </details>

          <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-white/10 bg-black/20 p-4 text-sm text-white/70">
            <input
              type="checkbox"
              checked={approved}
              onChange={(event) => setApproved(event.target.checked)}
              className="mt-1 h-4 w-4 accent-amber-400"
            />
            <span>
              <span className="block font-medium text-white/90">{ar ? "راجعت الاختيارات وأعتمد إنشاء مسودة فقط" : "I reviewed these selections and approve draft creation only"}</span>
              <span className="mt-1 block text-xs leading-5 text-white/45">
                {ar ? "لا يؤدي هذا إلى Post. سيعاد فحص الملف والـIDs على الخادم، وسيتم حفظ Gate الأصلي واختيارات المراجع في سجل التدقيق." : "This does not post. The server rechecks the file and live IDs and stores the original gate plus reviewer selections in the audit log."}
              </span>
            </span>
          </label>

          <button
            type="button"
            disabled={!canCreate}
            onClick={() => void createDraft()}
            className="w-full rounded-xl bg-emerald-400 px-5 py-3 text-sm font-bold text-black transition hover:bg-emerald-300 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {loading === "create" ? (ar ? "جاري إنشاء المسودة وربط المرفق..." : "Creating draft & attaching source...") : ar ? "اعتماد كمسودة في Odoo" : "Approve as Odoo Draft"}
          </button>
        </div>
      ) : null}

      {result ? (
        <div className={`rounded-xl border p-5 text-sm ${result.attachment_error ? "border-amber-400/30 bg-amber-400/10 text-amber-100" : "border-emerald-500/30 bg-emerald-500/10 text-emerald-100"}`}>
          <div className="text-base font-semibold">
            {ar ? `تم إنشاء/إعادة استخدام المسودة رقم ${result.odoo_draft.move_id}` : `Draft ${result.odoo_draft.move_id} created/reused`}
          </div>
          <div className="mt-2 grid gap-1 text-xs opacity-80">
            <span>{ar ? "الحالة" : "State"}: {result.odoo_draft.state}</span>
            <span>{ar ? "المرجع" : "Reference"}: {result.odoo_draft.ref}</span>
            <span>{ar ? "المرفق" : "Attachment"}: {result.attachment ? `#${result.attachment.attachment_id} · ${result.attachment.filename}` : ar ? "تعذر الربط ويمكن إعادة المحاولة" : "Attach failed; safely retryable"}</span>
            <span>{ar ? "الترحيل" : "Posting"}: {result.safety.posting_method_invoked ? "UNSAFE" : ar ? "لم يتم" : "Not invoked"}</span>
          </div>
          {result.attachment_error ? <div className="mt-3 text-xs">{result.attachment_error.code}: {result.attachment_error.message}</div> : null}
        </div>
      ) : null}
    </section>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-white/10 bg-black/20 p-4"><div className="text-xs text-white/40">{label}</div><div className="mt-1 truncate text-sm font-medium text-white/85">{value}</div></div>;
}

function TextField({ label, value, onChange, type = "text" }: { label: string; value: string; onChange: (value: string) => void; type?: string }) {
  return <label className="space-y-2 text-sm text-white/65"><span>{label}</span><input type={type} value={value} onChange={(event) => onChange(event.target.value)} className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-white outline-none focus:border-amber-400/50" /></label>;
}

function CandidateSelect({ label, rows, value, onChange, optional = false }: { label: string; rows: AccountingCandidate[]; value: number | null; onChange: (value: number | null) => void; optional?: boolean }) {
  const candidates = optionCandidates(rows);
  return (
    <label className="space-y-2 text-sm text-white/65">
      <span>{label}</span>
      <select value={value ?? ""} onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)} className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-white outline-none focus:border-amber-400/50">
        <option value="">{optional ? "—" : "Select…"}</option>
        {candidates.map((candidate) => <option key={candidate.id} value={candidate.id || ""}>{candidateLabel(candidate)}</option>)}
      </select>
    </label>
  );
}
