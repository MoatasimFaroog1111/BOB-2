"use client";

import { useCompany } from "@/lib/CompanyContext";
import { useLanguage } from "@/lib/LanguageContext";

export function CompanySelector() {
  const {
    companies,
    selectedCompanyId,
    selectedCompany,
    setSelectedCompanyId,
    loading,
    refreshCompanies,
  } = useCompany();
  const { language } = useLanguage();
  const ar = language === "ar";

  return (
    <section className="mb-5 rounded-xl border border-white/10 bg-white/[0.03] p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-white/40">
            {ar ? "الشركة الحالية" : "Current company"}
          </p>
          {selectedCompany ? (
            <p className="mt-1 truncate text-xs text-emerald-300" title={selectedCompany.name}>
              ● {selectedCompany.name}
            </p>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => void refreshCompanies()}
          disabled={loading}
          className="rounded-lg border border-white/10 px-2 py-1 text-[11px] text-white/50 transition hover:border-amber-400/30 hover:text-amber-300 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {loading ? (ar ? "تحميل..." : "Loading...") : ar ? "تحديث" : "Refresh"}
        </button>
      </div>

      <select
        aria-label={ar ? "اختيار الشركة" : "Select company"}
        value={selectedCompanyId ?? ""}
        onChange={(event) => {
          const next = Number.parseInt(event.target.value, 10);
          setSelectedCompanyId(Number.isSafeInteger(next) && next > 0 ? next : null);
        }}
        disabled={loading || companies.length === 0}
        className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-xs text-white outline-none transition focus:border-amber-400/50 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <option value="">
          {loading
            ? ar
              ? "جاري تحميل الشركات..."
              : "Loading companies..."
            : ar
              ? "اختر الشركة..."
              : "Select company..."}
        </option>
        {companies.map((company) => (
          <option key={company.id} value={company.id}>
            {company.name}{company.currency ? ` · ${company.currency}` : ""}
          </option>
        ))}
      </select>

      {!loading && companies.length === 0 ? (
        <p className="mt-2 text-[11px] leading-4 text-amber-200/70">
          {ar
            ? "لم يتم تحميل شركات Odoo. تحقق من اتصال النظام المحاسبي ثم اضغط تحديث."
            : "No Odoo companies were loaded. Check the accounting-system connection, then refresh."}
        </p>
      ) : null}
    </section>
  );
}
