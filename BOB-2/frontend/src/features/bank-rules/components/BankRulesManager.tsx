"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { bankRulesGateway } from "@/features/bank-rules/api/bankRulesGateway";
import {
  BankRuleEditor,
  type BankRuleEditorValue,
} from "@/features/bank-rules/components/BankRuleEditor";
import type {
  BankRule,
  BankRuleCondition,
  BankRuleVersion,
  ERPAccount,
  ERPJournal,
} from "@/features/bank-rules/model/types";
import { useLanguage } from "@/lib/LanguageContext";

interface EditorSession {
  mode: "create" | "edit_draft";
  ruleId?: number;
  versionId?: number;
}

interface TestResult {
  rule_id: number;
  version_id: number;
  version_number: number;
  tested_transaction_count: number;
  matched_transaction_count: number | null;
  sample_matches: Array<{
    row_number?: number;
    date?: string;
    description?: string;
    amount?: string;
  }>;
  note?: string;
}

function emptyEditor(journalId: number | null): BankRuleEditorValue {
  return {
    name: "",
    journalId,
    priority: 100,
    conditions: [{ field: "statement_text", operator: "contains", value: "" }],
    accountId: null,
    rationale: "",
    changeNote: "",
  };
}

function targetInput(version: BankRuleVersion | null | undefined) {
  return {
    account_id: Number(version?.target?.account_id || 0) || null,
    partner_id: Number(version?.target?.partner_id || 0) || null,
    analytic_account_id: Number(version?.target?.analytic_account_id || 0) || null,
  };
}

function conditionSummary(condition: BankRuleCondition, ar: boolean): string {
  const field = condition.field === "statement_text"
    ? (ar ? "النص" : "text")
    : condition.field === "amount"
      ? (ar ? "المبلغ" : "amount")
      : (ar ? "الاتجاه" : "direction");
  if (condition.operator === "between") {
    return `${field} between ${condition.min || "?"} .. ${condition.max || "?"}`;
  }
  return `${field} ${condition.operator} ${condition.value || "?"}`;
}

function statusBadge(rule: BankRule, ar: boolean): { label: string; className: string } {
  if (rule.is_enabled && rule.approved_version) {
    return {
      label: ar ? `نشطة — v${rule.approved_version.version_number}` : `Active — v${rule.approved_version.version_number}`,
      className: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
    };
  }
  if (rule.draft_version) {
    return {
      label: ar ? `مسودة — v${rule.draft_version.version_number}` : `Draft — v${rule.draft_version.version_number}`,
      className: "border-amber-500/30 bg-amber-500/10 text-amber-300",
    };
  }
  return {
    label: ar ? "غير مفعلة" : "Disabled",
    className: "border-white/10 bg-white/5 text-white/45",
  };
}

export function BankRulesManager() {
  const { language } = useLanguage();
  const ar = language === "ar";
  const [journals, setJournals] = useState<ERPJournal[]>([]);
  const [accounts, setAccounts] = useState<ERPAccount[]>([]);
  const [rules, setRules] = useState<BankRule[]>([]);
  const [selectedJournalId, setSelectedJournalId] = useState<number | null>(null);
  const [editorSession, setEditorSession] = useState<EditorSession | null>(null);
  const [editorValue, setEditorValue] = useState<BankRuleEditorValue>(() => emptyEditor(null));
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [testResults, setTestResults] = useState<Record<number, TestResult>>({});

  const selectedJournal = useMemo(
    () => journals.find((journal) => journal.id === selectedJournalId) || null,
    [journals, selectedJournalId],
  );

  const loadRules = useCallback(async (journalId?: number | null) => {
    const response = await bankRulesGateway.listRules(journalId || undefined);
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json();
    setRules(Array.isArray(data.items) ? data.items : []);
  }, []);

  const loadInitial = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [journalResponse, accountResponse] = await Promise.all([
        bankRulesGateway.listJournals(),
        bankRulesGateway.listAccounts(),
      ]);
      if (!journalResponse.ok) throw new Error(await journalResponse.text());
      if (!accountResponse.ok) throw new Error(await accountResponse.text());
      const journalRows = (await journalResponse.json()) as ERPJournal[];
      const accountRows = (await accountResponse.json()) as ERPAccount[];
      const banks = journalRows.filter((journal) => journal.type === "bank");
      setJournals(journalRows);
      setAccounts(accountRows);
      const firstJournal = banks[0]?.id || null;
      setSelectedJournalId(firstJournal);
      await loadRules(firstJournal);
    } catch (err: any) {
      setError(String(err?.message || err));
    } finally {
      setLoading(false);
    }
  }, [loadRules]);

  useEffect(() => {
    void loadInitial();
  }, [loadInitial]);

  const refreshRules = async (journalId = selectedJournalId) => {
    try {
      setError("");
      await loadRules(journalId);
    } catch (err: any) {
      setError(String(err?.message || err));
    }
  };

  const chooseJournal = async (journalId: number | null) => {
    setSelectedJournalId(journalId);
    setEditorSession(null);
    setEditorValue(emptyEditor(journalId));
    setNotice("");
    await refreshRules(journalId);
  };

  const beginCreate = () => {
    if (!selectedJournalId) {
      setError(ar ? "اختر يومية بنكية أولاً." : "Select a bank journal first.");
      return;
    }
    setError("");
    setNotice("");
    setEditorSession({ mode: "create" });
    setEditorValue(emptyEditor(selectedJournalId));
  };

  const beginEditDraft = (rule: BankRule) => {
    const version = rule.draft_version;
    if (!version) return;
    setError("");
    setNotice("");
    setEditorSession({ mode: "edit_draft", ruleId: rule.id, versionId: version.id });
    setEditorValue({
      name: rule.name,
      journalId: rule.journal_id,
      priority: rule.priority,
      conditions: version.conditions?.length
        ? version.conditions
        : [{ field: "statement_text", operator: "contains", value: "" }],
      accountId: Number(version.target?.account_id || 0) || null,
      rationale: version.rationale || "",
      changeNote: version.change_note || "",
    });
  };

  const saveEditor = async () => {
    if (!editorSession || actionLoading) return;
    if (!editorValue.name.trim() || !editorValue.journalId || !editorValue.accountId) {
      setError(ar ? "اسم القاعدة واليومية والحساب المقابل مطلوبة." : "Rule name, journal, and counterpart account are required.");
      return;
    }
    setActionLoading(true);
    setError("");
    setNotice("");
    try {
      const payload = {
        name: editorValue.name.trim(),
        journal_id: editorValue.journalId,
        priority: editorValue.priority,
        conditions: editorValue.conditions,
        target: { account_id: editorValue.accountId },
        rationale: editorValue.rationale,
        change_note: editorValue.changeNote,
      };
      let response: Response;
      if (editorSession.mode === "create") {
        response = await bankRulesGateway.createRule(payload);
      } else {
        response = await bankRulesGateway.editDraft(Number(editorSession.ruleId), {
          version_id: Number(editorSession.versionId),
          conditions: editorValue.conditions,
          target: { account_id: editorValue.accountId },
          rationale: editorValue.rationale,
          change_note: editorValue.changeNote,
        });
      }
      if (!response.ok) throw new Error(await response.text());
      setEditorSession(null);
      setEditorValue(emptyEditor(selectedJournalId));
      setNotice(ar ? "تم حفظ المسودة. لن تُستخدم في القيود قبل الاعتماد." : "Draft saved. It will not be used in entries until approved.");
      await loadRules(selectedJournalId || undefined);
    } catch (err: any) {
      setError(String(err?.message || err));
    } finally {
      setActionLoading(false);
    }
  };

  const importOdooRules = async () => {
    if (!selectedJournalId || actionLoading) return;
    setActionLoading(true);
    setError("");
    setNotice("");
    try {
      const response = await bankRulesGateway.importFromOdoo(selectedJournalId);
      if (!response.ok) throw new Error(await response.text());
      const result = await response.json();
      setNotice(
        ar
          ? `تم استيراد ${Number(result.imported_count || 0).toLocaleString()} قاعدة كمسودات فقط، وتجاوز ${Number(result.skipped_count || 0).toLocaleString()}. لا توجد أي عملية تفعيل تلقائي.`
          : `${Number(result.imported_count || 0).toLocaleString()} rules were imported as drafts only; ${Number(result.skipped_count || 0).toLocaleString()} skipped. Nothing was auto-activated.`,
      );
      await loadRules(selectedJournalId);
    } catch (err: any) {
      setError(String(err?.message || err));
    } finally {
      setActionLoading(false);
    }
  };

  const approveDraft = async (rule: BankRule) => {
    const draft = rule.draft_version;
    if (!draft || actionLoading) return;
    if (draft.source_snapshot?.import_requires_manual_configuration) {
      setError(
        ar
          ? "هذه القاعدة المستوردة تحتاج ضبط شروطها يدويًا قبل الاعتماد. اضغط «تعديل المسودة»."
          : "This imported rule requires manual condition mapping before approval. Edit the draft first.",
      );
      return;
    }
    setActionLoading(true);
    setError("");
    setNotice("");
    try {
      const response = await bankRulesGateway.approve(
        rule.id,
        draft.id,
        ar ? "اعتماد نسخة Bank Rule بعد التحقق من مراجع Odoo." : "Approved after validating live Odoo references.",
      );
      if (!response.ok) throw new Error(await response.text());
      setNotice(ar ? `تم اعتماد ${rule.name} v${draft.version_number}.` : `${rule.name} v${draft.version_number} approved.`);
      await loadRules(selectedJournalId || undefined);
    } catch (err: any) {
      setError(String(err?.message || err));
    } finally {
      setActionLoading(false);
    }
  };

  const createRevision = async (rule: BankRule) => {
    const approved = rule.approved_version;
    if (!approved || rule.draft_version || actionLoading) return;
    const accountId = Number(approved.target?.account_id || 0);
    if (!accountId) {
      setError(ar ? "النسخة المعتمدة لا تحتوي حساب Odoo صالحًا." : "Approved version has no valid Odoo account reference.");
      return;
    }
    setActionLoading(true);
    setError("");
    try {
      const response = await bankRulesGateway.createVersion(rule.id, {
        conditions: approved.conditions,
        target: {
          account_id: accountId,
          partner_id: approved.target?.partner_id || null,
          analytic_account_id: approved.target?.analytic_account_id || null,
        },
        rationale: approved.rationale || "",
        change_note: ar ? "مسودة تعديل جديدة" : "New revision draft",
      });
      if (!response.ok) throw new Error(await response.text());
      await loadRules(selectedJournalId || undefined);
      setNotice(ar ? "تم إنشاء نسخة مسودة جديدة. النسخة المعتمدة الحالية ما زالت فعالة حتى اعتماد المسودة." : "New draft version created. The currently approved version remains active until the draft is approved.");
    } catch (err: any) {
      setError(String(err?.message || err));
    } finally {
      setActionLoading(false);
    }
  };

  const disableRule = async (rule: BankRule) => {
    if (actionLoading || !rule.is_enabled) return;
    setActionLoading(true);
    setError("");
    try {
      const response = await bankRulesGateway.disable(
        rule.id,
        ar ? "تعطيل يدوي من صفحة إعدادات Bank Rules" : "Manually disabled from Bank Rules settings",
      );
      if (!response.ok) throw new Error(await response.text());
      await loadRules(selectedJournalId || undefined);
      setNotice(ar ? `تم تعطيل ${rule.name}.` : `${rule.name} disabled.`);
    } catch (err: any) {
      setError(String(err?.message || err));
    } finally {
      setActionLoading(false);
    }
  };

  const testRule = async (rule: BankRule, file: File | undefined) => {
    if (!file || actionLoading) return;
    setActionLoading(true);
    setError("");
    try {
      const response = await bankRulesGateway.testRule(rule.id, file);
      if (!response.ok) throw new Error(await response.text());
      const result = (await response.json()) as TestResult;
      setTestResults((current) => ({ ...current, [rule.id]: result }));
    } catch (err: any) {
      setError(String(err?.message || err));
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return <div className="p-8 text-sm text-white/50">{ar ? "جاري تحميل قواعد البنك..." : "Loading Bank Rules..."}</div>;
  }

  return (
    <div className="space-y-5 p-6" dir={ar ? "rtl" : "ltr"}>
      <section className="rounded-2xl border border-emerald-500/25 bg-emerald-500/[0.05] p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-4xl">
            <p className="text-[10px] font-black tracking-widest text-emerald-300">BOB BANK RULES ENGINE</p>
            <h1 className="mt-1 text-2xl font-black text-white">{ar ? "قواعد البنك" : "Bank Rules"}</h1>
            <p className="mt-2 text-sm leading-6 text-white/60">
              {ar
                ? "BOB هو مصدر الحقيقة لقواعد التصنيف. Odoo يُستخدم فقط للتحقق من اليومية والحسابات والشركاء والحسابات التحليلية الفعلية. المسودة لا تؤثر على القيود حتى تُختبر وتُعتمد."
                : "BOB is the source of truth for classification rules. Odoo is used only to verify live journals, accounts, partners, and analytic accounts. Drafts never affect entries until reviewed and approved."}
            </p>
          </div>
          <div className="rounded-xl border border-red-500/20 bg-red-500/[0.05] px-4 py-3 text-[10px] text-red-200">
            {ar ? "لا يوجد ترحيل إلى Odoo من هذه الصفحة" : "This page never posts to Odoo"}
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-white/10 bg-black/30 p-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-[280px] flex-1 space-y-1">
            <span className="text-[10px] font-bold text-white/50">{ar ? "اليومية البنكية" : "Bank journal"}</span>
            <select
              value={selectedJournalId || ""}
              onChange={(event) => void chooseJournal(Number(event.target.value) || null)}
              className="h-10 w-full rounded-xl border border-white/10 bg-black/30 px-3 text-xs text-white"
            >
              <option value="">{ar ? "اختر اليومية" : "Select journal"}</option>
              {journals.filter((journal) => journal.type === "bank").map((journal) => (
                <option key={journal.id} value={journal.id}>{journal.code} — {journal.name}</option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={beginCreate}
            disabled={!selectedJournalId || actionLoading}
            className="h-10 rounded-xl bg-amber-500 px-4 text-xs font-black text-black disabled:opacity-40"
          >
            + {ar ? "قاعدة جديدة" : "New Rule"}
          </button>
          <button
            type="button"
            onClick={() => void importOdooRules()}
            disabled={!selectedJournalId || actionLoading}
            className="h-10 rounded-xl border border-cyan-500/30 bg-cyan-500/5 px-4 text-xs font-bold text-cyan-200 disabled:opacity-40"
          >
            {ar ? "استيراد قواعد Odoo كمسودات" : "Import Odoo Rules as Drafts"}
          </button>
        </div>
        {selectedJournal && (
          <div className="mt-2 text-[9px] text-white/35">
            {ar ? "المصدر التنفيذي لليومية والحساب البنكي:" : "Live journal/account reference:"} {selectedJournal.code} — {selectedJournal.name}
          </div>
        )}
      </section>

      {editorSession && (
        <section className="rounded-2xl border border-amber-500/25 bg-amber-500/[0.04] p-5">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-black text-amber-200">
                {editorSession.mode === "create"
                  ? (ar ? "إنشاء مسودة قاعدة جديدة" : "Create new rule draft")
                  : (ar ? "تعديل النسخة المسودة" : "Edit draft version")}
              </h2>
              <p className="mt-1 text-[9px] text-white/40">
                {ar ? "الحفظ لا يفعّل القاعدة. الاعتماد إجراء منفصل." : "Saving does not activate the rule. Approval is a separate action."}
              </p>
            </div>
            <button type="button" onClick={() => setEditorSession(null)} className="text-xs text-white/50">✕</button>
          </div>
          <BankRuleEditor
            value={editorValue}
            onChange={setEditorValue}
            journals={journals}
            accounts={accounts}
            language={language}
            lockName={editorSession.mode === "edit_draft"}
            lockJournal={editorSession.mode === "edit_draft"}
            lockPriority={editorSession.mode === "edit_draft"}
          />
          <div className="mt-4 flex justify-end gap-2">
            <button type="button" onClick={() => setEditorSession(null)} className="rounded-lg border border-white/10 px-4 py-2 text-[10px] text-white/60">
              {ar ? "إلغاء" : "Cancel"}
            </button>
            <button type="button" onClick={() => void saveEditor()} disabled={actionLoading} className="rounded-lg bg-amber-500 px-5 py-2 text-[10px] font-black text-black disabled:opacity-40">
              {actionLoading ? "..." : (ar ? "حفظ كمسودة" : "Save Draft")}
            </button>
          </div>
        </section>
      )}

      {notice && <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/10 p-3 text-xs text-emerald-200">{notice}</div>}
      {error && <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-200 break-all">{error}</div>}

      <section className="space-y-3">
        {rules.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-white/10 p-8 text-center text-xs text-white/35">
            {ar
              ? "لا توجد قواعد BOB لهذه اليومية. يمكنك استيراد قواعد Odoo الحالية كمسودات أو إنشاء قواعد جديدة."
              : "No BOB rules exist for this journal. Import existing Odoo rules as drafts or create new rules."}
          </div>
        ) : rules.map((rule) => {
          const badge = statusBadge(rule, ar);
          const displayVersion = rule.draft_version || rule.approved_version || rule.latest_version;
          const warnings = Array.isArray(rule.draft_version?.source_snapshot?.import_warnings)
            ? rule.draft_version?.source_snapshot?.import_warnings as string[]
            : [];
          const requiresManual = Boolean(rule.draft_version?.source_snapshot?.import_requires_manual_configuration);
          const test = testResults[rule.id];
          return (
            <article key={rule.id} className="rounded-2xl border border-white/10 bg-black/30 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-sm font-black text-white">{rule.name}</h3>
                    <span className={`rounded-full border px-2 py-0.5 text-[9px] font-bold ${badge.className}`}>{badge.label}</span>
                    <span className="rounded-full border border-white/10 px-2 py-0.5 text-[9px] text-white/45">P{rule.priority}</span>
                    <span className="rounded-full border border-white/10 px-2 py-0.5 text-[9px] text-white/45">{rule.source_system}</span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {(displayVersion?.conditions || []).map((condition, index) => (
                      <span key={index} className="rounded bg-white/[0.05] px-2 py-1 text-[9px] text-white/55">{conditionSummary(condition, ar)}</span>
                    ))}
                    {(!displayVersion?.conditions || displayVersion.conditions.length === 0) && (
                      <span className="rounded bg-red-500/10 px-2 py-1 text-[9px] text-red-300">{ar ? "لا توجد شروط قابلة للتنفيذ" : "No executable conditions"}</span>
                    )}
                  </div>
                  <div className="mt-2 text-[10px] text-white/45">
                    {ar ? "الحساب:" : "Account:"} {displayVersion?.target?.account_code || ""} {displayVersion?.target?.account_name || displayVersion?.target?.account_id || "—"}
                  </div>
                  {displayVersion?.fingerprint && (
                    <div className="mt-1 truncate font-mono text-[8px] text-white/25">SHA-256 rule fingerprint: {displayVersion.fingerprint}</div>
                  )}
                  {warnings.length > 0 && (
                    <div className="mt-2 rounded-lg border border-amber-500/20 bg-amber-500/[0.05] p-2 text-[9px] text-amber-200">
                      {warnings.join(" · ")}
                    </div>
                  )}
                  {requiresManual && (
                    <div className="mt-2 text-[9px] font-bold text-red-300">
                      {ar ? "هذه المسودة لن تُعتمد حتى يتم تحويل شروط Odoo غير المدعومة إلى شروط BOB صريحة." : "This draft cannot be approved until unsupported Odoo conditions are mapped to explicit BOB conditions."}
                    </div>
                  )}
                </div>

                <div className="flex max-w-md flex-wrap justify-end gap-2">
                  {rule.draft_version && (
                    <button type="button" onClick={() => beginEditDraft(rule)} className="rounded-lg border border-amber-500/30 px-3 py-2 text-[10px] font-bold text-amber-300">
                      {ar ? "تعديل المسودة" : "Edit Draft"}
                    </button>
                  )}
                  {rule.draft_version && (
                    <button type="button" onClick={() => void approveDraft(rule)} disabled={actionLoading || requiresManual} className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-[10px] font-bold text-emerald-300 disabled:opacity-30">
                      {ar ? "اعتماد النسخة" : "Approve Version"}
                    </button>
                  )}
                  {rule.is_enabled && rule.approved_version && !rule.draft_version && (
                    <button type="button" onClick={() => void createRevision(rule)} disabled={actionLoading} className="rounded-lg border border-cyan-500/30 px-3 py-2 text-[10px] text-cyan-200 disabled:opacity-40">
                      {ar ? "إنشاء نسخة تعديل" : "Create Revision"}
                    </button>
                  )}
                  {rule.is_enabled && (
                    <button type="button" onClick={() => void disableRule(rule)} disabled={actionLoading} className="rounded-lg border border-red-500/25 px-3 py-2 text-[10px] text-red-300 disabled:opacity-40">
                      {ar ? "تعطيل" : "Disable"}
                    </button>
                  )}
                  <label className="cursor-pointer rounded-lg border border-white/15 px-3 py-2 text-[10px] text-white/65 hover:bg-white/5">
                    {ar ? "اختبار على كشف" : "Test on Statement"}
                    <input
                      type="file"
                      className="hidden"
                      disabled={actionLoading}
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        event.currentTarget.value = "";
                        void testRule(rule, file);
                      }}
                    />
                  </label>
                </div>
              </div>

              {test && (
                <div className="mt-3 rounded-xl border border-cyan-500/20 bg-cyan-500/[0.04] p-3">
                  <div className="text-[10px] font-bold text-cyan-200">
                    {ar ? "نتيجة الاختبار — بدون أي تعديل" : "Test result — no mutation"}: {test.matched_transaction_count ?? test.sample_matches.length} / {test.tested_transaction_count}
                  </div>
                  <div className="mt-2 max-h-40 space-y-1 overflow-y-auto">
                    {test.sample_matches.map((match, index) => (
                      <div key={index} className="grid grid-cols-[60px_90px_1fr_100px] gap-2 rounded bg-black/20 px-2 py-1 text-[9px] text-white/55">
                        <span>#{match.row_number ?? "-"}</span>
                        <span>{match.date || "-"}</span>
                        <span className="truncate">{match.description || "-"}</span>
                        <span className="text-end tabular-nums">{match.amount || "-"}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </article>
          );
        })}
      </section>
    </div>
  );
}
