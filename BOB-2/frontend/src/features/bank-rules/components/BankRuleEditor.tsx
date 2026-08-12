"use client";

import type { BankRuleCondition, ERPAccount, ERPJournal } from "@/features/bank-rules/model/types";

export interface BankRuleEditorValue {
  name: string;
  journalId: number | null;
  priority: number;
  conditions: BankRuleCondition[];
  accountId: number | null;
  rationale: string;
  changeNote: string;
}

interface BankRuleEditorProps {
  value: BankRuleEditorValue;
  onChange: (value: BankRuleEditorValue) => void;
  journals: ERPJournal[];
  accounts: ERPAccount[];
  language: string;
  lockJournal?: boolean;
  lockName?: boolean;
  lockPriority?: boolean;
}

const TEXT_OPERATORS = ["contains", "not_contains", "equals", "starts_with", "ends_with", "regex"];
const AMOUNT_OPERATORS = ["equals", "gt", "gte", "lt", "lte", "between"];

function newCondition(): BankRuleCondition {
  return { field: "statement_text", operator: "contains", value: "" };
}

export function BankRuleEditor({
  value,
  onChange,
  journals,
  accounts,
  language,
  lockJournal = false,
  lockName = false,
  lockPriority = false,
}: BankRuleEditorProps) {
  const ar = language === "ar";
  const updateCondition = (index: number, patch: Partial<BankRuleCondition>) => {
    const next = value.conditions.map((condition, position) =>
      position === index ? { ...condition, ...patch } : condition
    );
    onChange({ ...value, conditions: next });
  };

  const changeField = (index: number, field: BankRuleCondition["field"]) => {
    if (field === "direction") {
      updateCondition(index, { field, operator: "equals", value: "outflow", min: undefined, max: undefined });
      return;
    }
    if (field === "amount") {
      updateCondition(index, { field, operator: "equals", value: "0.00", min: undefined, max: undefined });
      return;
    }
    updateCondition(index, { field, operator: "contains", value: "", min: undefined, max: undefined });
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        <label className="space-y-1">
          <span className="text-[10px] font-bold text-white/55">{ar ? "اسم القاعدة" : "Rule name"}</span>
          <input
            value={value.name}
            disabled={lockName}
            onChange={(event) => onChange({ ...value, name: event.target.value })}
            className="h-10 w-full rounded-xl border border-white/10 bg-black/30 px-3 text-xs text-white outline-none focus:border-amber-500/50 disabled:opacity-50"
            placeholder={ar ? "مثال: Fees" : "Example: Fees"}
          />
        </label>
        <label className="space-y-1">
          <span className="text-[10px] font-bold text-white/55">{ar ? "اليومية البنكية" : "Bank journal"}</span>
          <select
            value={value.journalId || ""}
            disabled={lockJournal}
            onChange={(event) => onChange({ ...value, journalId: Number(event.target.value) || null })}
            className="h-10 w-full rounded-xl border border-white/10 bg-black/30 px-3 text-xs text-white outline-none focus:border-amber-500/50 disabled:opacity-50"
          >
            <option value="">{ar ? "اختر اليومية" : "Select journal"}</option>
            {journals.filter((journal) => journal.type === "bank").map((journal) => (
              <option key={journal.id} value={journal.id}>{journal.code} — {journal.name}</option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className="text-[10px] font-bold text-white/55">{ar ? "الأولوية" : "Priority"}</span>
          <input
            type="number"
            min={0}
            max={100000}
            value={value.priority}
            disabled={lockPriority}
            onChange={(event) => onChange({ ...value, priority: Math.max(0, Number(event.target.value) || 0) })}
            className="h-10 w-full rounded-xl border border-white/10 bg-black/30 px-3 text-xs text-white outline-none focus:border-amber-500/50 disabled:opacity-50"
          />
          <span className="block text-[9px] text-white/30">{ar ? "الرقم الأقل = أولوية أعلى" : "Lower number = higher priority"}</span>
        </label>
      </div>

      <div className="rounded-xl border border-white/10 bg-black/20 p-3">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <div className="text-xs font-bold text-white">{ar ? "شروط المطابقة — جميعها AND" : "Match conditions — all are AND"}</div>
            <div className="mt-1 text-[9px] text-white/40">
              {ar ? "لا توجد مطابقة تقريبية أو حساب احتياطي. يجب أن تتحقق جميع الشروط." : "No fuzzy matching or fallback account. Every condition must pass."}
            </div>
          </div>
          <button
            type="button"
            onClick={() => onChange({ ...value, conditions: [...value.conditions, newCondition()] })}
            disabled={value.conditions.length >= 12}
            className="rounded-lg border border-amber-500/30 px-3 py-2 text-[10px] font-bold text-amber-300 disabled:opacity-30"
          >
            + {ar ? "شرط" : "Condition"}
          </button>
        </div>

        <div className="space-y-2">
          {value.conditions.map((condition, index) => {
            const operators = condition.field === "statement_text"
              ? TEXT_OPERATORS
              : condition.field === "amount"
                ? AMOUNT_OPERATORS
                : ["equals"];
            return (
              <div key={index} className="grid gap-2 rounded-lg border border-white/5 bg-white/[0.025] p-2 md:grid-cols-[160px_150px_1fr_auto]">
                <select
                  value={condition.field}
                  onChange={(event) => changeField(index, event.target.value as BankRuleCondition["field"])}
                  className="h-9 rounded-lg border border-white/10 bg-black/35 px-2 text-[10px] text-white"
                >
                  <option value="statement_text">{ar ? "نص الحركة" : "Statement text"}</option>
                  <option value="amount">{ar ? "المبلغ" : "Amount"}</option>
                  <option value="direction">{ar ? "الاتجاه" : "Direction"}</option>
                </select>
                <select
                  value={condition.operator}
                  onChange={(event) => updateCondition(index, { operator: event.target.value })}
                  className="h-9 rounded-lg border border-white/10 bg-black/35 px-2 text-[10px] text-white"
                >
                  {operators.map((operator) => <option key={operator} value={operator}>{operator}</option>)}
                </select>

                {condition.field === "direction" ? (
                  <select
                    value={condition.value || "outflow"}
                    onChange={(event) => updateCondition(index, { value: event.target.value })}
                    className="h-9 rounded-lg border border-white/10 bg-black/35 px-2 text-[10px] text-white"
                  >
                    <option value="outflow">{ar ? "خروج من البنك" : "Outflow"}</option>
                    <option value="inflow">{ar ? "دخول إلى البنك" : "Inflow"}</option>
                  </select>
                ) : condition.field === "amount" && condition.operator === "between" ? (
                  <div className="grid grid-cols-2 gap-2">
                    <input
                      inputMode="decimal"
                      value={condition.min || ""}
                      onChange={(event) => updateCondition(index, { min: event.target.value })}
                      placeholder={ar ? "من" : "Min"}
                      className="h-9 rounded-lg border border-white/10 bg-black/35 px-2 text-[10px] text-white"
                    />
                    <input
                      inputMode="decimal"
                      value={condition.max || ""}
                      onChange={(event) => updateCondition(index, { max: event.target.value })}
                      placeholder={ar ? "إلى" : "Max"}
                      className="h-9 rounded-lg border border-white/10 bg-black/35 px-2 text-[10px] text-white"
                    />
                  </div>
                ) : (
                  <input
                    value={condition.value || ""}
                    onChange={(event) => updateCondition(index, { value: event.target.value })}
                    placeholder={condition.field === "statement_text" ? "INSTANT PAYMENT FEES" : "1.15"}
                    className="h-9 rounded-lg border border-white/10 bg-black/35 px-2 text-[10px] text-white outline-none focus:border-amber-500/40"
                  />
                )}

                <button
                  type="button"
                  onClick={() => onChange({ ...value, conditions: value.conditions.filter((_, position) => position !== index) })}
                  disabled={value.conditions.length <= 1}
                  className="h-9 rounded-lg border border-red-500/20 px-3 text-[10px] text-red-300 disabled:opacity-20"
                  aria-label={ar ? "حذف الشرط" : "Remove condition"}
                >
                  ×
                </button>
              </div>
            );
          })}
        </div>
      </div>

      <label className="block space-y-1">
        <span className="text-[10px] font-bold text-white/55">{ar ? "الحساب المقابل — من Odoo فقط" : "Counterpart account — Odoo only"}</span>
        <select
          value={value.accountId || ""}
          onChange={(event) => onChange({ ...value, accountId: Number(event.target.value) || null })}
          className="h-10 w-full rounded-xl border border-white/10 bg-black/30 px-3 text-xs text-white outline-none focus:border-amber-500/50"
        >
          <option value="">{ar ? "اختر حسابًا فعليًا من Odoo" : "Select a live Odoo account"}</option>
          {accounts.map((account) => (
            <option key={account.id} value={account.id}>{account.code} — {account.name}</option>
          ))}
        </select>
      </label>

      <div className="grid gap-3 md:grid-cols-2">
        <label className="space-y-1">
          <span className="text-[10px] font-bold text-white/55">{ar ? "مبرر القاعدة" : "Rule rationale"}</span>
          <textarea
            value={value.rationale}
            onChange={(event) => onChange({ ...value, rationale: event.target.value })}
            maxLength={4000}
            className="min-h-20 w-full rounded-xl border border-white/10 bg-black/30 p-3 text-xs text-white outline-none focus:border-amber-500/50"
          />
        </label>
        <label className="space-y-1">
          <span className="text-[10px] font-bold text-white/55">{ar ? "ملاحظة التغيير" : "Change note"}</span>
          <textarea
            value={value.changeNote}
            onChange={(event) => onChange({ ...value, changeNote: event.target.value })}
            maxLength={4000}
            className="min-h-20 w-full rounded-xl border border-white/10 bg-black/30 p-3 text-xs text-white outline-none focus:border-amber-500/50"
          />
        </label>
      </div>
    </div>
  );
}
