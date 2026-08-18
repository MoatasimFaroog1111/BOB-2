"use client";

import type { OdooJournal } from "@/features/documents/model/types";
import {
  formatAccountingMoney,
  type SmartAccountantCandidateLine,
  type SmartAccountantVerification,
} from "@/features/documents/model/smartAccountantWorkspace";

export function SmartAccountantContextView({
  language,
  company,
  selectedJournal,
  accountCount,
  partnerCount,
  analyticCount,
  lines,
  verification,
  currency,
  onPrepareEntry,
}: Readonly<{
  language: string;
  company: { id: number; name: string; currency: string } | null;
  selectedJournal: OdooJournal | null;
  accountCount: number;
  partnerCount: number;
  analyticCount: number;
  lines: SmartAccountantCandidateLine[];
  verification: SmartAccountantVerification;
  currency: string;
  onPrepareEntry: () => void;
}>) {
  const ar = language === "ar";

  return (
    <div className="flex-1 overflow-y-auto p-3">
      <section className="rounded-xl border border-white/10 bg-white/[0.025] p-3">
        <div className="flex items-center justify-between gap-2">
          <div>
            <div className="text-[9px] font-bold text-white/50">
              {ar ? "درجة التحقق" : "Verification score"}
            </div>
            <div className="mt-1 text-2xl font-black text-white">{verification.score}%</div>
          </div>
          <div className="whitespace-pre-line text-left text-[8px] leading-relaxed text-white/35">
            {ar ? "ليست ثقة نموذج\nبل تحقق من بيانات فعلية" : "Not model confidence\nVerified data checks"}
          </div>
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10">
          <div className="h-full rounded-full bg-emerald-400" style={{ width: `${verification.score}%` }} />
        </div>
      </section>

      <section className="mt-3 rounded-xl border border-white/10 bg-white/[0.025] p-3">
        <h3 className="text-[10px] font-bold text-white/75">{ar ? "السياق المحاسبي" : "Accounting context"}</h3>
        <dl className="mt-2 space-y-2 text-[9.5px]">
          <ContextRow label={ar ? "الشركة" : "Company"} value={company?.name || "—"} />
          <ContextRow
            label={ar ? "اليومية" : "Journal"}
            value={selectedJournal ? `${selectedJournal.name} (${selectedJournal.code})` : "—"}
          />
          <ContextRow label={ar ? "شجرة الحسابات" : "Accounts"} value={accountCount.toLocaleString()} />
          <ContextRow label={ar ? "الشركاء" : "Partners"} value={partnerCount.toLocaleString()} />
          <ContextRow label={ar ? "مراكز التكلفة" : "Analytic accounts"} value={analyticCount.toLocaleString()} />
        </dl>
      </section>

      <section className="mt-3 rounded-xl border border-white/10 bg-white/[0.025] p-3">
        <h3 className="text-[10px] font-bold text-white/75">{ar ? "أدلة التحقق" : "Verification evidence"}</h3>
        <div className="mt-2 space-y-1.5 text-[9px]">
          <EvidenceRow ok={Boolean(company)} text={ar ? "شركة محددة في السياق" : "Company selected in context"} />
          <EvidenceRow ok={Boolean(selectedJournal)} text={ar ? "يومية Odoo محددة" : "Odoo journal selected"} />
          <EvidenceRow ok={lines.length >= 2} text={ar ? "يوجد سطران محاسبيان على الأقل" : "At least two accounting lines"} />
          <EvidenceRow ok={verification.balanced} text={ar ? "إجمالي المدين يساوي الدائن" : "Debit equals credit"} />
          <EvidenceRow
            ok={verification.accountCodeCount > 0 && verification.rowsWithKnownAccounts === verification.accountCodeCount}
            text={
              ar
                ? `${verification.rowsWithKnownAccounts}/${verification.accountCodeCount} حسابات مطابقة لشجرة Odoo`
                : `${verification.rowsWithKnownAccounts}/${verification.accountCodeCount} account codes matched in Odoo`
            }
          />
          {verification.partnerCount > 0 && (
            <EvidenceRow
              ok={verification.rowsWithKnownPartners === verification.partnerCount}
              text={
                ar
                  ? `${verification.rowsWithKnownPartners}/${verification.partnerCount} شركاء مطابقون`
                  : `${verification.rowsWithKnownPartners}/${verification.partnerCount} partners matched`
              }
            />
          )}
          {verification.analyticCount > 0 && (
            <EvidenceRow
              ok={verification.rowsWithKnownAnalytics === verification.analyticCount}
              text={
                ar
                  ? `${verification.rowsWithKnownAnalytics}/${verification.analyticCount} مراكز تكلفة مطابقة`
                  : `${verification.rowsWithKnownAnalytics}/${verification.analyticCount} analytic accounts matched`
              }
            />
          )}
        </div>
      </section>

      <section className="mt-3 rounded-xl border border-white/10 bg-white/[0.025] p-3">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-[10px] font-bold text-white/75">{ar ? "معاينة القيد" : "Journal preview"}</h3>
          <span className="text-[8px] text-white/35">{lines.length} {ar ? "سطور" : "lines"}</span>
        </div>
        <div className="mt-2 space-y-1.5">
          {lines.slice(0, 4).map((line, index) => (
            <div key={`${line.accountCode}-${index}`} className="rounded-lg border border-white/5 bg-black/20 p-2">
              <div className="flex items-center justify-between gap-2 text-[9px]">
                <span className="truncate font-bold text-white/75">{line.accountCode || (ar ? "غير محدد" : "Unresolved")}</span>
                <span className={line.debit > 0 ? "text-emerald-300" : "text-amber-300"}>
                  {formatAccountingMoney(line.debit || line.credit, currency)}
                </span>
              </div>
              <div className="mt-1 truncate text-[8.5px] text-white/40">{line.description || line.partnerName || "—"}</div>
            </div>
          ))}
          {lines.length === 0 && (
            <p className="rounded-lg border border-dashed border-white/10 p-3 text-center text-[9px] text-white/35">
              {ar ? "أدخل أو ارفع بيانات لعرض المعاينة والأدلة." : "Enter or upload data to show preview and evidence."}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={onPrepareEntry}
          className="mt-2 w-full rounded-lg bg-gradient-to-r from-amber-500 to-yellow-500 px-3 py-2 text-[9.5px] font-black text-black transition hover:from-amber-400 hover:to-yellow-400"
        >
          {ar ? "مراجعة القيد قبل التسجيل" : "Review entry before registration"}
        </button>
      </section>
    </div>
  );
}

function ContextRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-white/40">{label}</dt>
      <dd className="max-w-[65%] truncate font-semibold text-white/75">{value}</dd>
    </div>
  );
}

function EvidenceRow({ ok, text }: { ok: boolean; text: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg bg-black/15 px-2 py-1.5">
      <span className={ok ? "text-emerald-300" : "text-amber-300"}>{ok ? "✓" : "!"}</span>
      <span className={ok ? "text-white/65" : "text-amber-200/75"}>{text}</span>
    </div>
  );
}
