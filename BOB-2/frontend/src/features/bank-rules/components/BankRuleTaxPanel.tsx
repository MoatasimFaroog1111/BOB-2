"use client";

import { useCallback, useEffect, useState } from "react";

import { bankRulesGateway } from "@/features/bank-rules/api/bankRulesGateway";
import type { BankRule, ERPTax } from "@/features/bank-rules/model/types";
import { API_BASE_URL } from "@/lib/api";
import { useLanguage } from "@/lib/LanguageContext";

interface ReferenceCatalogWithTaxes {
  taxes?: ERPTax[];
}

export function BankRuleTaxPanel() {
  const { language } = useLanguage();
  const ar = language === "ar";
  const [rules, setRules] = useState<BankRule[]>([]);
  const [taxes, setTaxes] = useState<ERPTax[]>([]);
  const [ruleId, setRuleId] = useState<number | null>(null);
  const [taxId, setTaxId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const [rulesResponse, catalog] = await Promise.all([
        bankRulesGateway.listRules(),
        bankRulesGateway.referenceCatalog() as unknown as Promise<ReferenceCatalogWithTaxes>,
      ]);
      if (!rulesResponse.ok) throw new Error(await rulesResponse.text());
      const rulesBody = await rulesResponse.json();
      const draftRules = (Array.isArray(rulesBody.items) ? rulesBody.items : []).filter(
        (item: BankRule) => Boolean(item.draft_version),
      );
      setRules(draftRules);
      setTaxes(Array.isArray(catalog.taxes) ? catalog.taxes : []);
      setRuleId((current) => current && draftRules.some((item: BankRule) => item.id === current)
        ? current
        : draftRules[0]?.id || null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const rule = rules.find((item) => item.id === ruleId);
    setTaxId(Number(rule?.draft_version?.target?.tax_id || 0) || null);
  }, [ruleId, rules]);

  const save = async () => {
    const rule = rules.find((item) => item.id === ruleId);
    const versionId = rule?.draft_version?.id;
    if (!rule || !versionId || busy) return;
    setBusy(true);
    setMessage("");
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/bank-rules/${rule.id}/draft-tax`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version_id: versionId, tax_id: taxId }),
      });
      if (!response.ok) throw new Error(await response.text());
      setMessage(
        ar
          ? "تم حفظ الضريبة على المسودة. سيتم التحقق منها مرة أخرى من Odoo عند الاعتماد، ولن تؤثر على القيود قبل الاعتماد."
          : "Tax saved on the draft. Odoo revalidates it again at approval, and it cannot affect entries before approval.",
      );
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mx-6 mb-6 rounded-2xl border border-cyan-500/25 bg-cyan-500/[0.04] p-5" dir={ar ? "rtl" : "ltr"}>
      <div className="mb-4">
        <div className="text-[10px] font-black tracking-widest text-cyan-300">BANK RULE TAX</div>
        <h2 className="mt-1 text-lg font-black text-white">{ar ? "معالجة الضريبة في قواعد البنك" : "Bank Rule Tax Handling"}</h2>
        <p className="mt-2 text-xs leading-5 text-white/55">
          {ar
            ? "اربط الضريبة بمسودة القاعدة. بعد الاعتماد، مبلغ البنك يُعامل كإجمالي شامل الضريبة ويُقسّم إلى صافي + ضريبة + بنك، مع بقاء القيد متوازنًا."
            : "Assign a tax to a rule draft. After approval, the bank cash amount is treated as gross and split into base + tax + bank while preserving a balanced entry."}
        </p>
      </div>

      <div className="grid gap-3 md:grid-cols-[1.2fr_1.2fr_auto]">
        <label className="space-y-1">
          <span className="text-[10px] font-bold text-white/55">{ar ? "مسودة القاعدة" : "Rule draft"}</span>
          <select
            value={ruleId || ""}
            onChange={(event) => setRuleId(Number(event.target.value) || null)}
            className="h-10 w-full rounded-xl border border-white/10 bg-black/30 px-3 text-xs text-white"
          >
            <option value="">{ar ? "اختر مسودة" : "Select a draft"}</option>
            {rules.map((rule) => (
              <option key={rule.id} value={rule.id}>{rule.name} — v{rule.draft_version?.version_number}</option>
            ))}
          </select>
        </label>

        <label className="space-y-1">
          <span className="text-[10px] font-bold text-white/55">{ar ? "ضريبة Odoo" : "Odoo tax"}</span>
          <select
            value={taxId || ""}
            onChange={(event) => setTaxId(Number(event.target.value) || null)}
            disabled={!ruleId}
            className="h-10 w-full rounded-xl border border-white/10 bg-black/30 px-3 text-xs text-white disabled:opacity-40"
          >
            <option value="">{ar ? "بدون ضريبة" : "No tax"}</option>
            {taxes.map((tax) => (
              <option key={tax.id} value={tax.id}>{tax.name} — {tax.amount}% ({tax.type_tax_use || "general"})</option>
            ))}
          </select>
        </label>

        <button
          type="button"
          onClick={() => void save()}
          disabled={!ruleId || busy}
          className="self-end h-10 rounded-xl bg-cyan-400 px-5 text-xs font-black text-black disabled:opacity-40"
        >
          {busy ? "..." : ar ? "حفظ الضريبة" : "Save Tax"}
        </button>
      </div>

      {message && <div className="mt-3 rounded-lg border border-emerald-500/20 bg-emerald-500/10 p-2 text-[10px] text-emerald-200">{message}</div>}
      {error && <div className="mt-3 rounded-lg border border-red-500/20 bg-red-500/10 p-2 text-[10px] text-red-200 break-all">{error}</div>}
      {rules.length === 0 && (
        <div className="mt-3 text-[10px] text-white/35">{ar ? "أنشئ أو افتح نسخة مسودة أولًا لإضافة الضريبة." : "Create or open a draft version first to configure tax."}</div>
      )}
    </section>
  );
}
