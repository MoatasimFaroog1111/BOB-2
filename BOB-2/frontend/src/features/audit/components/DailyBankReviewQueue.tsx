"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { dailyBankAuditGateway } from "@/features/audit/api/dailyBankAuditGateway";
import { useLanguage } from "@/lib/LanguageContext";

interface QueueItem {
  approval_id: number;
  status: string;
  entry_date?: string | null;
  transaction_count?: number | null;
  unresolved_count?: number | null;
  low_confidence_count?: number | null;
  total_debit?: string | null;
  total_credit?: string | null;
  source_document?: { document_id?: number; filename?: string; sha256?: string };
  bank_journal?: { journal_name?: string; journal_code?: string; bank_account_code?: string };
  audit_result?: AuditResult | null;
}

interface AuditFinding {
  severity: "error" | "warning" | "info" | string;
  code: string;
  title: string;
  reason: string;
  evidence?: Record<string, unknown>;
  suggested_action?: string;
  source_row?: number | null;
}

interface AuditResult {
  risk_level: string;
  recommendation: string;
  blocking_count: number;
  warning_count: number;
  findings: AuditFinding[];
  source_hash_verified?: boolean;
  audited_at?: string;
}

interface ReviewDetail extends QueueItem {
  package?: {
    entry?: {
      entry_date?: string;
      journal_name?: string;
      transaction_count?: number;
      total_debit?: string;
      total_credit?: string;
      lines?: Array<Record<string, any>>;
    };
    source_document?: { document_id?: number; filename?: string; sha256?: string };
    bank_journal?: Record<string, any>;
    audit_result?: AuditResult;
  };
}

function statusLabel(status: string, language: string): string {
  const ar: Record<string, string> = {
    pending_audit: "بانتظار التدقيق",
    awaiting_human_approval: "بانتظار الاعتماد البشري",
    needs_revision: "يحتاج تعديل",
    approved: "معتمد داخليًا",
  };
  const en: Record<string, string> = {
    pending_audit: "Pending audit",
    awaiting_human_approval: "Awaiting human approval",
    needs_revision: "Needs revision",
    approved: "Internally approved",
  };
  return (language === "ar" ? ar : en)[status] || status;
}

function severityClass(severity: string): string {
  if (severity === "error") return "border-red-500/40 bg-red-500/10 text-red-100";
  if (severity === "warning") return "border-amber-500/40 bg-amber-500/10 text-amber-100";
  return "border-emerald-500/30 bg-emerald-500/10 text-emerald-100";
}

export function DailyBankReviewQueue() {
  const { language } = useLanguage();
  const [items, setItems] = useState<QueueItem[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState("");
  const [decisionNote, setDecisionNote] = useState("");

  const loadQueue = useCallback(async (autoOpen = false) => {
    try {
      const response = await dailyBankAuditGateway.listQueue();
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json();
      const rows = Array.isArray(data.items) ? data.items : [];
      setItems(rows);
      if (rows.length > 0) {
        setSelectedId((current) => current || Number(rows[0].approval_id));
        if (autoOpen && rows.some((row: QueueItem) => row.status === "pending_audit")) setOpen(true);
      }
    } catch (err: any) {
      setError(String(err?.message || err));
    }
  }, []);

  const loadDetail = useCallback(async (approvalId: number) => {
    setLoading(true);
    setError("");
    try {
      const response = await dailyBankAuditGateway.getReview(approvalId);
      if (!response.ok) throw new Error(await response.text());
      setDetail(await response.json());
    } catch (err: any) {
      setError(String(err?.message || err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadQueue(true);
  }, [loadQueue]);

  useEffect(() => {
    if (selectedId) loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  const pendingCount = useMemo(
    () => items.filter((item) => item.status === "pending_audit" || item.status === "awaiting_human_approval").length,
    [items],
  );

  const runAudit = async () => {
    if (!selectedId || actionLoading) return;
    setActionLoading(true);
    setError("");
    try {
      const response = await dailyBankAuditGateway.runAudit(selectedId);
      if (!response.ok) throw new Error(await response.text());
      setDetail(await response.json());
      await loadQueue();
    } catch (err: any) {
      setError(String(err?.message || err));
    } finally {
      setActionLoading(false);
    }
  };

  const decide = async (decision: "approve" | "return") => {
    if (!selectedId || actionLoading) return;
    setActionLoading(true);
    setError("");
    try {
      const response = await dailyBankAuditGateway.decide(selectedId, decision, decisionNote);
      if (!response.ok) throw new Error(await response.text());
      setDetail(await response.json());
      setDecisionNote("");
      await loadQueue();
    } catch (err: any) {
      setError(String(err?.message || err));
    } finally {
      setActionLoading(false);
    }
  };

  const openSource = async () => {
    const documentId = Number(detail?.package?.source_document?.document_id || detail?.source_document?.document_id || 0);
    if (!documentId) return;
    setActionLoading(true);
    setError("");
    try {
      const response = await dailyBankAuditGateway.fetchSourceDocument(documentId);
      if (!response.ok) throw new Error(await response.text());
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err: any) {
      setError(String(err?.message || err));
    } finally {
      setActionLoading(false);
    }
  };

  const entry = detail?.package?.entry;
  const findings = detail?.audit_result?.findings || detail?.package?.audit_result?.findings || [];

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed z-[125] bottom-4 right-4 h-11 px-4 rounded-xl border border-amber-500/50 bg-[#180c04]/95 text-amber-300 text-xs font-bold shadow-2xl backdrop-blur-xl"
      >
        {language === "ar" ? "تدقيق قيود البنك" : "Bank Entry Audit"}
        {pendingCount > 0 && <span className="ms-2 rounded-full bg-red-500 text-white px-2 py-0.5 text-[10px]">{pendingCount}</span>}
      </button>

      {open && (
        <div className="fixed inset-0 z-[130] bg-black/75 backdrop-blur-sm p-4 md:p-8" dir={language === "ar" ? "rtl" : "ltr"}>
          <div className="mx-auto flex h-full max-w-7xl flex-col overflow-hidden rounded-2xl border border-amber-500/30 bg-[#120803] shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
              <div>
                <h2 className="text-base font-black text-amber-300">
                  {language === "ar" ? "المدقق الذكي — قيود البنك اليومية" : "Smart Auditor — Daily Bank Entries"}
                </h2>
                <p className="mt-1 text-[11px] text-white/55">
                  {language === "ar"
                    ? "تدقيق مستقل للقيد، كشف البنك، نسخة BOB Bank Rule المعتمدة، مراجع Odoo وسلسلة الأدلة. لا يوجد ترحيل إلى Odoo من هذه الشاشة."
                    : "Independent audit of the journal entry, bank statement, approved BOB Bank Rule version, live Odoo references, and evidence chain. This screen never posts to Odoo."}
                </p>
              </div>
              <button type="button" onClick={() => setOpen(false)} className="rounded-lg border border-white/15 px-3 py-1.5 text-xs text-white/70 hover:text-white">✕</button>
            </div>

            <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[320px_1fr]">
              <aside className="overflow-y-auto border-e border-white/10 bg-black/20 p-3">
                <button type="button" onClick={() => loadQueue()} className="mb-3 w-full rounded-lg border border-white/10 py-2 text-[11px] text-white/70 hover:bg-white/5">
                  {language === "ar" ? "تحديث قائمة المراجعة" : "Refresh review queue"}
                </button>
                {items.length === 0 && <div className="p-4 text-center text-xs text-white/40">{language === "ar" ? "لا توجد قيود مرسلة للمراجعة." : "No entries have been sent for review."}</div>}
                <div className="space-y-2">
                  {items.map((item) => (
                    <button
                      key={item.approval_id}
                      type="button"
                      onClick={() => setSelectedId(item.approval_id)}
                      className={`w-full rounded-xl border p-3 text-start transition-all ${selectedId === item.approval_id ? "border-amber-500/60 bg-amber-500/10" : "border-white/10 bg-white/[0.03] hover:bg-white/[0.06]"}`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-bold text-white">{item.entry_date || "-"}</span>
                        <span className="text-[9px] text-amber-300">#{item.approval_id}</span>
                      </div>
                      <div className="mt-1 text-[10px] text-white/55">{item.bank_journal?.journal_name || "-"}</div>
                      <div className="mt-2 flex flex-wrap gap-1 text-[9px]">
                        <span className="rounded bg-white/10 px-1.5 py-0.5 text-white/65">{statusLabel(item.status, language)}</span>
                        <span className="rounded bg-white/10 px-1.5 py-0.5 text-white/65">{item.transaction_count || 0} {language === "ar" ? "حركة" : "txns"}</span>
                        {(item.unresolved_count || 0) > 0 && <span className="rounded bg-red-500/15 px-1.5 py-0.5 text-red-300">{item.unresolved_count} {language === "ar" ? "غير محلول" : "unresolved"}</span>}
                      </div>
                    </button>
                  ))}
                </div>
              </aside>

              <main className="min-w-0 overflow-y-auto p-4 md:p-5">
                {loading && <div className="py-12 text-center text-sm text-white/50">{language === "ar" ? "جاري تحميل ملف التدقيق..." : "Loading audit package..."}</div>}
                {!loading && detail && (
                  <div className="space-y-4">
                    <section className="grid grid-cols-2 gap-2 md:grid-cols-5">
                      {[
                        [language === "ar" ? "التاريخ" : "Date", detail.entry_date || entry?.entry_date || "-"],
                        [language === "ar" ? "الحركات" : "Transactions", String(detail.transaction_count || entry?.transaction_count || 0)],
                        [language === "ar" ? "إجمالي المدين" : "Total debit", String(detail.total_debit || entry?.total_debit || "0.00")],
                        [language === "ar" ? "إجمالي الدائن" : "Total credit", String(detail.total_credit || entry?.total_credit || "0.00")],
                        [language === "ar" ? "الحالة" : "Status", statusLabel(detail.status, language)],
                      ].map(([label, value]) => (
                        <div key={label} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                          <div className="text-[9px] text-white/40">{label}</div>
                          <div className="mt-1 text-xs font-bold text-white">{value}</div>
                        </div>
                      ))}
                    </section>

                    <section className="rounded-xl border border-white/10 bg-black/20 p-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <div className="text-xs font-bold text-white">{detail.source_document?.filename || detail.package?.source_document?.filename || "Bank statement"}</div>
                          <div className="mt-1 font-mono text-[9px] text-white/35 break-all">SHA-256: {detail.source_document?.sha256 || detail.package?.source_document?.sha256 || "-"}</div>
                        </div>
                        <button type="button" onClick={openSource} disabled={actionLoading} className="rounded-lg border border-amber-500/30 px-3 py-2 text-[10px] font-bold text-amber-300 hover:bg-amber-500/10 disabled:opacity-50">
                          {language === "ar" ? "فتح المستند الأصلي" : "Open source document"}
                        </button>
                      </div>
                    </section>

                    <section className="overflow-hidden rounded-xl border border-white/10">
                      <div className="border-b border-white/10 bg-white/[0.03] px-4 py-2 text-xs font-bold text-white">
                        {language === "ar" ? "تفاصيل القيد ودليل Bank Rule" : "Journal lines and Bank Rule evidence"}
                      </div>
                      <div className="overflow-x-auto">
                        <table className="min-w-[1050px] w-full text-[10px] text-white/75">
                          <thead className="bg-black/30 text-white/45">
                            <tr>
                              <th className="p-2 text-start">{language === "ar" ? "سطر المصدر" : "Source row"}</th>
                              <th className="p-2 text-start">{language === "ar" ? "الحساب" : "Account"}</th>
                              <th className="p-2 text-start">{language === "ar" ? "البيان" : "Description"}</th>
                              <th className="p-2 text-end">{language === "ar" ? "مدين" : "Debit"}</th>
                              <th className="p-2 text-end">{language === "ar" ? "دائن" : "Credit"}</th>
                              <th className="p-2 text-start">Bank Rule</th>
                              <th className="p-2 text-start">{language === "ar" ? "الثقة" : "Confidence"}</th>
                              <th className="p-2 text-start">{language === "ar" ? "الدليل" : "Evidence"}</th>
                            </tr>
                          </thead>
                          <tbody>
                            {(entry?.lines || []).map((line, index) => (
                              <tr key={`${line.transaction_key || index}-${line.role || index}`} className="border-t border-white/5">
                                <td className="p-2">{String(line.source_row ?? "")}</td>
                                <td className="p-2">{String(line.account_code || "—")} {String(line.account_name || "")}</td>
                                <td className="max-w-[280px] p-2">{String(line.name || "")}</td>
                                <td className="p-2 text-end tabular-nums">{String(line.debit || "")}</td>
                                <td className="p-2 text-end tabular-nums">{String(line.credit || "")}</td>
                                <td className="p-2">{line.role === "bank" ? (language === "ar" ? "حساب اليومية البنكية" : "Bank journal account") : String(line.bank_rule_name || "—")}</td>
                                <td className="p-2">{line.role === "counterpart" ? `${Math.round(Number(line.confidence || 0) * 100)}%` : ""}</td>
                                <td className="max-w-[300px] p-2 text-white/50">{String(line.reason || line.evidence_source || "")}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </section>

                    <section className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
                      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                        <div className="text-xs font-bold text-white">{language === "ar" ? "نتيجة التدقيق" : "Audit result"}</div>
                        {detail.audit_result && (
                          <div className="flex gap-2 text-[9px]">
                            <span className="rounded bg-red-500/15 px-2 py-1 text-red-300">{detail.audit_result.blocking_count} {language === "ar" ? "مانع" : "blocking"}</span>
                            <span className="rounded bg-amber-500/15 px-2 py-1 text-amber-300">{detail.audit_result.warning_count} {language === "ar" ? "تحذير" : "warnings"}</span>
                            <span className="rounded bg-white/10 px-2 py-1 text-white/65">{detail.audit_result.risk_level}</span>
                          </div>
                        )}
                      </div>

                      {findings.length === 0 ? (
                        <div className="text-[11px] text-white/45">{language === "ar" ? "لم يتم تشغيل التدقيق على هذا القيد بعد." : "Audit has not been run for this entry yet."}</div>
                      ) : (
                        <div className="space-y-2">
                          {findings.map((finding, index) => (
                            <div key={`${finding.code}-${index}`} className={`rounded-xl border p-3 ${severityClass(finding.severity)}`}>
                              <div className="flex items-center justify-between gap-2">
                                <span className="text-[10px] font-black">{finding.code}</span>
                                {finding.source_row != null && <span className="text-[9px] opacity-70">{language === "ar" ? "سطر" : "Row"} {finding.source_row}</span>}
                              </div>
                              <div className="mt-1 text-xs font-bold">{finding.title}</div>
                              <div className="mt-1 text-[10px] opacity-80">{finding.reason}</div>
                              {finding.suggested_action && <div className="mt-2 text-[10px] font-semibold">→ {finding.suggested_action}</div>}
                            </div>
                          ))}
                        </div>
                      )}
                    </section>

                    <section className="rounded-xl border border-amber-500/20 bg-amber-500/[0.04] p-4">
                      <textarea
                        value={decisionNote}
                        onChange={(event) => setDecisionNote(event.target.value)}
                        placeholder={language === "ar" ? "ملاحظة المراجع/المعتمد..." : "Reviewer/approver note..."}
                        className="mb-3 min-h-20 w-full rounded-lg border border-white/10 bg-black/30 p-3 text-xs text-white outline-none focus:border-amber-500/40"
                      />
                      <div className="flex flex-wrap gap-2">
                        <button type="button" onClick={runAudit} disabled={actionLoading || detail.status === "approved"} className="rounded-lg bg-amber-500 px-4 py-2 text-[11px] font-black text-black disabled:opacity-40">
                          {actionLoading ? "..." : (language === "ar" ? "تشغيل التدقيق الذكي" : "Run Smart Audit")}
                        </button>
                        <button type="button" onClick={() => decide("return")} disabled={actionLoading || detail.status === "approved"} className="rounded-lg border border-red-500/40 px-4 py-2 text-[11px] font-bold text-red-300 disabled:opacity-40">
                          {language === "ar" ? "إرجاع للمحاسب للتعديل" : "Return for Revision"}
                        </button>
                        <button type="button" onClick={() => decide("approve")} disabled={actionLoading || detail.status !== "awaiting_human_approval"} className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-[11px] font-bold text-emerald-300 disabled:opacity-40">
                          {language === "ar" ? "اعتماد التدقيق بشريًا" : "Human Approve Audit"}
                        </button>
                      </div>
                      <div className="mt-2 text-[9px] text-white/40">
                        {language === "ar" ? "الاعتماد هنا داخلي فقط ولا يرحّل القيد إلى Odoo. الترحيل يبقى إجراءً منفصلًا بصلاحية مستقلة." : "Approval here is internal only and does not post to Odoo. ERP posting remains a separate permissioned action."}
                      </div>
                    </section>
                  </div>
                )}

                {error && <div className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-[10px] text-red-200 break-all">{error}</div>}
              </main>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
