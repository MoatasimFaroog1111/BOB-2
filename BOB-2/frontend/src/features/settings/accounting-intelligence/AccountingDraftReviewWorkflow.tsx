"use client";

import { useMemo, useState } from "react";

import {
  analyzeAccountingDocument,
  createReviewedAccountingDraft,
  fetchAccountingReviewCatalog,
  type AccountingCandidate,
  type AccountingDocumentReviewResult,
  type AccountingReviewCatalog,
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

function mergeCandidates(primary: AccountingCandidate[], catalog: AccountingCandidate[] = []) {
  const byId = new Map<number, AccountingCandidate>();
  for (const row of catalog) {
    if (row.id) byId.set(Number(row.id), { ...row, live_reference_resolved: true });
  }
  for (const row of primary) {
    if (row.id) byId.set(Number(row.id), { ...byId.get(Number(row.id)), ...row });
  }
  return [...byId.values()].sort((left, right) => {
    if (Boolean(left.selected) !== Boolean(right.selected)) return left.selected ? -1 : 1;
    const leftScore = left.model_score ?? left.confidence ?? -1;
    const rightScore = right.model_score ?? right.confidence ?? -1;
    if (leftScore !== rightScore) return rightScore - leftScore;
    return candidateLabel(left).localeCompare(candidateLabel(right));
  });
}

export function AccountingDraftReviewWorkflow() {
  const { language } = useLanguage();
  const ar = language === "ar";
  const [file, setFile] = useState<File | null>(null);
  const [analysis, setAnalysis] = useState<AccountingDocumentReviewResult | null>(null);
  const [catalog, setCatalog] = useState<AccountingReviewCatalog | null>(null);
  const [catalogError, setCatalogError] = useState("");
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
  const moveTypeReviewRequired = useMemo(() => {
    if (!analysis) return false;
    const selected = analysis.prediction.move_type.filter((row) => row.selected);
    return selected.length !== 1 || selected[0]?.label !== "entry";
  }, [analysis]);

  const journals = useMemo(
    () => mergeCandidates(analysis?.prediction.journals || [], catalog?.journals),
    [analysis, catalog],
  );
  const accounts = useMemo(
    () => mergeCandidates(
      [...(analysis?.prediction.debit_accounts || []), ...(analysis?.prediction.credit_accounts || [])],
      catalog?.accounts,
    ),
    [analysis, catalog],
  );
  const partners = useMemo(
    () => mergeCandidates(analysis?.partner_candidates || [], catalog?.partners),
    [analysis, catalog],
  );
  const analytics = useMemo(
    () => mergeCandidates(analysis?.prediction.analytic_accounts || [], catalog?.analytics),
    [analysis, catalog],
  );

  const resetReview = () => {
    setAnalysis(null);
    setCatalog(null);
    setCatalogError("");
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
    setCatalogError("");
    setResult(null);
    try {
      const next = await analyzeAccountingDocument(file, companyId, amount || undefined);
      setAnalysis(next);
      setAmount(next.document.detected_amount != null ? String(next.document.detected_amount) : amount);
      setEntryDate(next.document.detected_entry_date || "");
      setDescription(next.source.filename || file.name);
      setJournalId(next.review_defaults.journal_id);
      setDebitAccountId(next.review_defaults.debit_account_id);
      setCreditAccountId(next.review_defaults.credit_account_id);
      setDebitPartnerId(next.review_defaults.debit_partner_id);
      setCreditPartnerId(next.review_defaults.credit_partner_id);
      setDebitAnalyticId(next.review_defaults.debit_analytic_id);
      setCreditAnalyticId(next.review_defaults.credit_analytic_id);
      setApproved(false);

      try {
        setCatalog(await fetchAccountingReviewCatalog(companyId));
      } catch {
        setCatalog(null);
        setCatalogError(
          ar
            ? "تعذر تحميل الكتالوج الكامل من Odoo؛ ما زالت توصيات V2 الحية متاحة للمراجعة."
            : "The full Odoo catalog could not be loaded; live V2 candidates remain available for review.",
        );
      }
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
      !moveTypeReviewRequired &&
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
      {catalogError ? <div className="rounded-xl border border-amber-400/20 bg-amber-400/[0.06] p-3 text-xs text-amber-100/80">{catalogError}</div> : null}

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
                ? "البوابة الأصلية ما زالت محجوبة ولم نخفض أي Threshold. هذا المسار يسمح بالإنشاء فقط بعد مراجعتك الصريحة للاختيارات أدناه."
                : "The original gate remains blocked and no threshold is lowered. Creation is allowed only after your explicit review of the selections below."}
            </div>
          ) : null}

          {moveTypeReviewRequired ? (
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">
              {ar
                ? "هذا المسار خاص بقيود Journal Entry فقط، بينما V2 لم يصنف المستند كـ entry. لن يتم تغيير نوع العملية قسرًا."
                : "This workflow is restricted to journal entries, while V2 did not classify the document as an entry. The transaction type will not be forced."}
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
            <SearchableCandidateSelect label={ar ? "الدفتر" : "Journal"} rows={journals} value={journalId} onChange={setJournalId} ar={ar} />
            <SearchableCandidateSelect label={ar ? "الحساب المدين" : "Debit account"} rows={accounts} value={debitAccountId} onChange={setDebitAccountId} ar={ar} />
            <SearchableCandidateSelect label={ar ? "الحساب الدائن" : "Credit account"} rows={accounts} value={creditAccountId} onChange={setCreditAccountId} ar={ar} />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <SearchableCandidateSelect
              label={`${ar ? "شريك السطر المدين" : "Debit-line partner"}${analysis.review_defaults.counterpart_side === "debit" ? " ★" : ""}`}
              rows={partners}
              value={debitPartnerId}
              onChange={setDebitPartnerId}
              optional
              ar={ar}
            />
            <SearchableCandidateSelect
              label={`${ar ? "شريك السطر الدائن" : "Credit-line partner"}${analysis.review_defaults.counterpart_side === "credit" ? " ★" : ""}`}
              rows={partners}
              value={creditPartnerId}
              onChange={setCreditPartnerId}
              optional
              ar={ar}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <SearchableCandidateSelect
              label={ar ? "تحليلي السطر المدين (100%)" : "Debit analytic (100%)"}
              rows={analytics}
              value={debitAnalyticId}
              onChange={setDebitAnalyticId}
              optional
              ar={ar}
            />
            <SearchableCandidateSelect
              label={ar ? "تحليلي السطر الدائن (100%)" : "Credit analytic (100%)"}
              rows={analytics}
              value={creditAnalyticId}
              onChange={setCreditAnalyticId}
              optional
              ar={ar}
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

function SearchableCandidateSelect({
  label,
  rows,
  value,
  onChange,
  optional = false,
  ar,
}: {
  label: string;
  rows: AccountingCandidate[];
  value: number | null;
  onChange: (value: number | null) => void;
  optional?: boolean;
  ar: boolean;
}) {
  const [query, setQuery] = useState("");
  const normalized = query.trim().toLocaleLowerCase();
  const filtered = rows.filter((row) => {
    if (!normalized) return true;
    return candidateLabel(row).toLocaleLowerCase().includes(normalized);
  });
  const selected = value ? rows.find((row) => Number(row.id) === value) : null;
  const visible = filtered.slice(0, 60);
  if (selected && !visible.some((row) => Number(row.id) === value)) visible.unshift(selected);

  return (
    <label className="space-y-2 text-sm text-white/65">
      <span>{label}</span>
      {rows.length > 12 ? (
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={ar ? "بحث بالاسم أو الكود..." : "Search name or code..."}
          className="w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs text-white outline-none focus:border-amber-400/40"
        />
      ) : null}
      <select
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}
        className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-white outline-none focus:border-amber-400/50"
      >
        <option value="">{optional ? "—" : ar ? "اختر..." : "Select..."}</option>
        {visible.map((candidate) => (
          <option key={candidate.id} value={candidate.id || ""}>{candidateLabel(candidate)}</option>
        ))}
      </select>
      {rows.length > visible.length ? <span className="block text-[11px] text-white/35">{ar ? `استخدم البحث للوصول إلى ${rows.length} مرجع حي` : `Use search across ${rows.length} live references`}</span> : null}
    </label>
  );
}
