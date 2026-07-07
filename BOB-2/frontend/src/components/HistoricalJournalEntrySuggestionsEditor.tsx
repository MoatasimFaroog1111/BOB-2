"use client";

import { useEffect, useMemo, useState } from "react";
import { API_BASE_URL } from "@/lib/api";
import JournalEntrySuggestionsEditor from "@/components/JournalEntrySuggestionsEditor";

interface Transaction {
  date: string;
  description: string;
  amount: number;
  row_number: number;
  suggested_action?: string;
  suggested_action_label?: string;
  confidence?: number;
  explanation?: string;
  detected_category?: string;
  ai_suggested_account?: string;
}

interface Props {
  rows: Transaction[];
  isAr: boolean;
  bankAccountLabel?: string;
  companyId?: number | null;
  bankJournalId?: number | string | null;
  bankAccountId?: number | null;
}

interface HistoricalSuggestion {
  row_number?: number | null;
  date?: string;
  amount?: number;
  suggested_account_label?: string;
  suggested_partner_label?: string;
  suggested_analytic_account_label?: string;
  confidence?: number;
  reason?: string;
  historical_move_name?: string;
  historical_date?: string;
  needs_review?: boolean;
}

function keyFor(row: Pick<Transaction, "row_number" | "date" | "amount">) {
  return `${row.row_number ?? ""}|${row.date || ""}|${Number(row.amount || 0).toFixed(2)}`;
}

function pct(value?: number) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

export default function HistoricalJournalEntrySuggestionsEditor({ rows, isAr, bankAccountLabel = "", companyId, bankJournalId, bankAccountId }: Props) {
  const [enhancedRows, setEnhancedRows] = useState<Transaction[]>(rows);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const payload = useMemo(() => ({
    transactions: rows,
    company_id: companyId || null,
    bank_journal_id: bankJournalId ? Number(bankJournalId) : null,
    bank_account_id: bankAccountId || null,
    history_limit: 600,
  }), [rows, companyId, bankJournalId, bankAccountId]);

  useEffect(() => {
    let alive = true;
    async function loadHistoricalSuggestions() {
      if (!rows.length) {
        setEnhancedRows([]);
        return;
      }
      setLoading(true);
      setError("");
      setNotice("");
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/erp/bank-reconciliation/entry-suggestions`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await response.json().catch(() => null);
        if (!response.ok) throw new Error(data?.detail || `Error ${response.status}`);

        const suggestions = new Map<string, HistoricalSuggestion>();
        (Array.isArray(data?.items) ? data.items : []).forEach((item: HistoricalSuggestion) => {
          suggestions.set(keyFor({ row_number: Number(item.row_number || 0), date: item.date || "", amount: Number(item.amount || 0) }), item);
        });

        const nextRows = rows.map((row) => {
          const item = suggestions.get(keyFor(row));
          if (!item || !item.suggested_account_label) return row;
          const historicalParts = [
            item.suggested_account_label,
            item.suggested_partner_label,
            item.suggested_analytic_account_label,
          ].filter(Boolean);
          const reason = item.reason || "Historical Odoo suggestion";
          return {
            ...row,
            ai_suggested_account: historicalParts.join(" | "),
            confidence: Math.max(Number(row.confidence || 0), Number(item.confidence || 0)),
            suggested_action_label: item.needs_review
              ? (row.suggested_action_label || (isAr ? "يحتاج مراجعة" : "Needs review"))
              : `${isAr ? "اقتراح تاريخي من أودو" : "Historical Odoo suggestion"} ${pct(item.confidence)}`,
            explanation: `${row.explanation || ""}${row.explanation ? " | " : ""}${reason}`,
          };
        });

        if (!alive) return;
        setEnhancedRows(nextRows);
        setNotice(isAr
          ? `تم بناء القيود المقترحة من ${data?.history_count || 0} قيد بنكي تاريخي منشور في أودو. الاقتراحات الواثقة: ${data?.confident_count || 0}.`
          : `Proposed entries were built from ${data?.history_count || 0} posted historical Odoo bank entries. Confident suggestions: ${data?.confident_count || 0}.`);
      } catch (err: any) {
        if (!alive) return;
        setEnhancedRows(rows);
        setError((isAr ? "تعذر قراءة البيانات التاريخية من أودو: " : "Could not read historical Odoo data: ") + (err?.message || err));
      } finally {
        if (alive) setLoading(false);
      }
    }
    loadHistoricalSuggestions();
    return () => { alive = false; };
  }, [payload, rows, isAr]);

  return (
    <>
      <div className="fixed top-5 right-5 z-[10001] max-w-xl space-y-2 text-xs">
        {loading && <div className="rounded-xl border border-cyan-500/40 bg-cyan-500/15 px-4 py-2 font-bold text-cyan-200 shadow-2xl">{isAr ? "جاري قراءة القيود التاريخية من أودو وبناء الاقتراحات..." : "Reading historical Odoo entries and building suggestions..."}</div>}
        {notice && <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/15 px-4 py-2 font-bold text-emerald-200 shadow-2xl">{notice}</div>}
        {error && <div className="rounded-xl border border-amber-500/40 bg-amber-500/15 px-4 py-2 font-bold text-amber-200 shadow-2xl">{error}</div>}
      </div>
      <JournalEntrySuggestionsEditor rows={enhancedRows} isAr={isAr} bankAccountLabel={bankAccountLabel} />
    </>
  );
}
