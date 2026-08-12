"use client";

import { useCallback, useEffect, useState } from "react";

import { dailyBankAuditGateway } from "@/features/audit/api/dailyBankAuditGateway";
import { useLanguage } from "@/lib/LanguageContext";

interface ReviewItem {
  approval_id: number;
  entry_date?: string | null;
  status: string;
  source_document?: { filename?: string };
}

interface SupportingEvidence {
  document_id: number;
  filename: string;
  content_type?: string;
  size?: number;
  sha256?: string;
  attached_at?: string;
}

export function DailyBankEvidenceManager() {
  const { language } = useLanguage();
  const [open, setOpen] = useState(false);
  const [reviews, setReviews] = useState<ReviewItem[]>([]);
  const [approvalId, setApprovalId] = useState<number | null>(null);
  const [evidence, setEvidence] = useState<SupportingEvidence[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadReviews = useCallback(async () => {
    const response = await dailyBankAuditGateway.listQueue();
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json();
    const items = (Array.isArray(data.items) ? data.items : []) as ReviewItem[];
    setReviews(items);
    setApprovalId((current) => current || (items[0]?.approval_id ? Number(items[0].approval_id) : null));
  }, []);

  const loadEvidence = useCallback(async (id: number) => {
    const response = await dailyBankAuditGateway.listSupportingDocuments(id);
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json();
    setEvidence(Array.isArray(data.items) ? data.items : []);
  }, []);

  useEffect(() => {
    loadReviews().catch((err) => setError(String(err?.message || err)));
  }, [loadReviews]);

  useEffect(() => {
    if (!approvalId) {
      setEvidence([]);
      return;
    }
    loadEvidence(approvalId).catch((err) => setError(String(err?.message || err)));
  }, [approvalId, loadEvidence]);

  const current = reviews.find((item) => item.approval_id === approvalId) || null;
  const evidenceLocked = current ? !["pending_audit", "needs_revision"].includes(current.status) : true;

  const attachFiles = async (files: FileList | null) => {
    if (!approvalId || !files?.length || evidenceLocked) return;
    setLoading(true);
    setError("");
    try {
      const selected = Array.from(files).slice(0, 20);
      const response = await dailyBankAuditGateway.attachSupportingDocuments(approvalId, selected);
      if (!response.ok) throw new Error(await response.text());
      await loadEvidence(approvalId);
    } catch (err: any) {
      setError(String(err?.message || err));
    } finally {
      setLoading(false);
    }
  };

  const openEvidence = async (item: SupportingEvidence) => {
    if (!approvalId) return;
    setLoading(true);
    setError("");
    try {
      const response = await dailyBankAuditGateway.fetchSupportingDocument(approvalId, item.document_id);
      if (!response.ok) throw new Error(await response.text());
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err: any) {
      setError(String(err?.message || err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed z-[124] bottom-4 right-44 h-11 px-4 rounded-xl border border-cyan-500/40 bg-[#071218]/95 text-cyan-200 text-xs font-bold shadow-2xl backdrop-blur-xl"
      >
        {language === "ar" ? "مستندات المراجعة" : "Audit Evidence"}
      </button>

      {open && (
        <div className="fixed inset-0 z-[140] bg-black/75 backdrop-blur-sm p-4 md:p-8" dir={language === "ar" ? "rtl" : "ltr"}>
          <div className="mx-auto max-w-3xl overflow-hidden rounded-2xl border border-cyan-500/30 bg-[#071218] shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
              <div>
                <h2 className="text-sm font-black text-cyan-200">
                  {language === "ar" ? "المستندات المؤيدة للقيد" : "Supporting Evidence"}
                </h2>
                <p className="mt-1 text-[10px] text-white/50">
                  {language === "ar"
                    ? "كل مستند يُحفظ داخل نطاق المؤسسة ويُختم بـ SHA-256 ويُعاد التحقق منه أثناء التدقيق."
                    : "Every document is tenant-isolated, SHA-256 sealed, and re-verified when Smart Audit runs."}
                </p>
              </div>
              <button type="button" onClick={() => setOpen(false)} className="rounded-lg border border-white/15 px-3 py-1.5 text-xs text-white/70">✕</button>
            </div>

            <div className="p-5 space-y-4">
              <label className="block">
                <span className="mb-1 block text-[10px] font-bold text-white/60">
                  {language === "ar" ? "اختر القيد اليومي" : "Select daily entry"}
                </span>
                <select
                  value={approvalId || ""}
                  onChange={(event) => setApprovalId(Number(event.target.value) || null)}
                  className="h-10 w-full rounded-xl border border-white/10 bg-black/30 px-3 text-xs text-white outline-none"
                >
                  {reviews.length === 0 && <option value="">{language === "ar" ? "لا توجد قيود مراجعة" : "No review entries"}</option>}
                  {reviews.map((item) => (
                    <option key={item.approval_id} value={item.approval_id}>
                      #{item.approval_id} — {item.entry_date || "-"} — {item.source_document?.filename || "Bank statement"} — {item.status}
                    </option>
                  ))}
                </select>
              </label>

              <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="text-xs font-bold text-white">
                      {language === "ar" ? "إرفاق مستندات مؤيدة" : "Attach supporting documents"}
                    </div>
                    <div className="mt-1 text-[9px] text-white/45">
                      {evidenceLocked
                        ? (language === "ar" ? "تم قفل الأدلة بعد التدقيق/الاعتماد. أعد القيد للتعديل قبل إضافة مستندات." : "Evidence is locked after audit/approval. Return the package for revision before adding documents.")
                        : (language === "ar" ? "يمكن إرفاق فاتورة، إيصال، موافقة، أمر شراء أو أي مستند مؤيد مسموح به." : "Attach invoices, receipts, approvals, purchase orders, or any allowed supporting evidence.")}
                    </div>
                  </div>
                  <label className={`rounded-lg px-4 py-2 text-[10px] font-bold ${evidenceLocked ? "cursor-not-allowed bg-white/5 text-white/25" : "cursor-pointer bg-cyan-500 text-black"}`}>
                    {loading ? "..." : (language === "ar" ? "اختيار ملفات" : "Choose files")}
                    <input
                      type="file"
                      multiple
                      disabled={loading || evidenceLocked}
                      onChange={(event) => {
                        void attachFiles(event.target.files);
                        event.currentTarget.value = "";
                      }}
                      className="hidden"
                    />
                  </label>
                </div>
              </div>

              <div className="space-y-2">
                {evidence.length === 0 && (
                  <div className="rounded-xl border border-dashed border-white/10 p-5 text-center text-[10px] text-white/35">
                    {language === "ar" ? "لا توجد مستندات مؤيدة إضافية لهذا القيد حتى الآن." : "No additional supporting evidence has been attached yet."}
                  </div>
                )}
                {evidence.map((item) => (
                  <div key={item.document_id} className="rounded-xl border border-white/10 bg-black/20 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-xs font-bold text-white">{item.filename}</div>
                        <div className="mt-1 text-[9px] text-white/40">
                          {Number(item.size || 0).toLocaleString()} bytes · ID {item.document_id}
                        </div>
                        <div className="mt-1 break-all font-mono text-[8px] text-cyan-200/45">SHA-256: {item.sha256 || "-"}</div>
                      </div>
                      <button
                        type="button"
                        disabled={loading}
                        onClick={() => void openEvidence(item)}
                        className="shrink-0 rounded-lg border border-cyan-500/30 px-3 py-2 text-[10px] font-bold text-cyan-200 disabled:opacity-40"
                      >
                        {language === "ar" ? "فتح" : "Open"}
                      </button>
                    </div>
                  </div>
                ))}
              </div>

              {error && <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-[10px] text-red-200 break-all">{error}</div>}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
