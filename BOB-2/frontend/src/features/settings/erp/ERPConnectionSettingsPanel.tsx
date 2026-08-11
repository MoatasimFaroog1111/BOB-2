"use client";

import { useCompany } from "@/lib/CompanyContext";

import { ERP_PROVIDERS, getERPProviderDefinition } from "./providers";
import type { ERPProviderId } from "./types";
import { useERPConnectionSettings } from "./useERPConnectionSettings";

const inputClass =
  "w-full rounded-xl border border-white/15 bg-black/35 px-3 py-2.5 text-sm text-white outline-none transition focus:border-amber-400/70";

export function ERPConnectionSettingsPanel() {
  const { refreshCompanies } = useCompany();
  const {
    form,
    setForm,
    selectProvider,
    savedConnection,
    testResult,
    loading,
    working,
    error,
    message,
    testDraft,
    testSaved,
    save,
  } = useERPConnectionSettings(refreshCompanies);

  const provider = getERPProviderDefinition(form.provider);

  if (loading) {
    return <div className="p-6 text-sm text-white/60">جارٍ تحميل إعدادات النظام المحاسبي…</div>;
  }

  return (
    <div className="space-y-6 p-6" dir="rtl">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs font-semibold tracking-wider text-amber-400">ACCOUNTING SYSTEMS</p>
          <h1 className="mt-1 text-2xl font-bold text-white">الاتصال بالأنظمة المحاسبية</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-white/55">
            اختر النظام المحاسبي، اختبر الاتصال، ثم احفظ بيانات الاعتماد المشفرة. يدعم الاتصال Odoo وSAP وOracle وBusiness Central وQuickBooks وXero.
          </p>
        </div>
        <div className="rounded-2xl border border-white/10 bg-black/30 px-5 py-3 text-sm">
          <p className="text-white/45">الحالة</p>
          <p className={`mt-1 font-semibold ${savedConnection?.is_active ? "text-emerald-400" : "text-amber-400"}`}>
            {savedConnection?.is_active ? "متصل ومحفوظ" : "لا يوجد اتصال محفوظ"}
          </p>
          {savedConnection?.provider ? (
            <p className="mt-1 text-xs text-white/45">{getERPProviderDefinition((savedConnection.provider as ERPProviderId) || "odoo").label}</p>
          ) : null}
        </div>
      </div>

      {error ? (
        <div className="rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-200">{error}</div>
      ) : null}
      {message ? (
        <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-4 text-sm text-emerald-200">{message}</div>
      ) : null}

      <section className="rounded-2xl border border-white/10 bg-black/30 p-5">
        <div className="grid gap-4 md:grid-cols-2">
          <label className="space-y-2 text-sm text-white/75 md:col-span-2">
            <span className="block font-medium">مزود النظام</span>
            <select
              value={form.provider}
              onChange={(event) => selectProvider(event.target.value as ERPProviderId)}
              className={inputClass}
            >
              {ERP_PROVIDERS.map((item) => (
                <option key={item.id} value={item.id}>{item.label}</option>
              ))}
            </select>
            <span className="block text-xs leading-5 text-white/45">{provider.authHint}</span>
          </label>

          <label className="space-y-2 text-sm text-white/75">
            <span className="block font-medium">{provider.urlLabel}</span>
            <input
              type="url"
              value={form.url}
              onChange={(event) => setForm((current) => ({ ...current, url: event.target.value }))}
              placeholder={provider.urlPlaceholder}
              className={inputClass}
            />
          </label>

          <label className="space-y-2 text-sm text-white/75">
            <span className="block font-medium">{provider.dbLabel}</span>
            <input
              value={form.db}
              onChange={(event) => setForm((current) => ({ ...current, db: event.target.value }))}
              placeholder={provider.dbPlaceholder}
              className={inputClass}
            />
          </label>

          <label className="space-y-2 text-sm text-white/75">
            <span className="block font-medium">{provider.usernameLabel}</span>
            <input
              autoComplete="username"
              value={form.username}
              onChange={(event) => setForm((current) => ({ ...current, username: event.target.value }))}
              placeholder={provider.usernamePlaceholder}
              className={inputClass}
            />
          </label>

          <label className="space-y-2 text-sm text-white/75">
            <span className="block font-medium">
              {savedConnection && savedConnection.provider === form.provider
                ? `${provider.passwordLabel} الجديد`
                : provider.passwordLabel}
            </span>
            <input
              type="password"
              autoComplete="new-password"
              value={form.password}
              onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
              placeholder={provider.passwordPlaceholder}
              className={inputClass}
            />
          </label>
        </div>

        <div className="mt-5 rounded-xl border border-white/10 bg-white/[0.025] p-3 text-xs leading-5 text-white/45">
          الاتصالات الخارجية تمر عبر سياسة Allowlist وDNS/IP validation الخاصة بالمشروع. يجب إضافة نطاق خادم النظام إلى ERP_OUTBOUND_ALLOWED_HOSTS قبل الاتصال في بيئة الإنتاج.
        </div>

        <div className="mt-5 flex flex-wrap justify-end gap-3">
          {savedConnection ? (
            <button
              type="button"
              disabled={working}
              onClick={() => void testSaved()}
              className="rounded-xl border border-white/15 px-5 py-2.5 text-sm font-medium text-white/80 disabled:opacity-40"
            >
              اختبار الاتصال المحفوظ
            </button>
          ) : null}
          <button
            type="button"
            disabled={working}
            onClick={() => void testDraft()}
            className="rounded-xl border border-amber-500/40 px-5 py-2.5 text-sm font-medium text-amber-300 disabled:opacity-40"
          >
            اختبار البيانات المدخلة
          </button>
          <button
            type="button"
            disabled={working}
            onClick={() => void save()}
            className="rounded-xl bg-amber-500 px-6 py-2.5 text-sm font-semibold text-black disabled:opacity-40"
          >
            {working ? "جارٍ التنفيذ…" : savedConnection ? "تحديث الاتصال" : "حفظ الاتصال"}
          </button>
        </div>
      </section>

      {testResult ? (
        <section className="rounded-2xl border border-white/10 bg-black/30 p-5">
          <h2 className="text-lg font-semibold text-white">نتيجة الاختبار</h2>
          <div className="mt-4 grid gap-3 text-sm md:grid-cols-3">
            <div className="rounded-xl border border-white/10 p-3">
              <p className="text-white/45">الاتصال</p>
              <p className={testResult.connected ? "mt-1 text-emerald-400" : "mt-1 text-red-300"}>
                {testResult.connected ? "ناجح" : "فاشل"}
              </p>
            </div>
            <div className="rounded-xl border border-white/10 p-3">
              <p className="text-white/45">النظام</p>
              <p className="mt-1 text-white/80">
                {typeof testResult.system === "string" ? testResult.system : provider.label}
              </p>
            </div>
            <div className="rounded-xl border border-white/10 p-3">
              <p className="text-white/45">الإصدار / المستخدم</p>
              <p className="mt-1 text-white/80">
                {testResult.odoo_version?.server_version || testResult.uid || "تم التحقق"}
              </p>
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
}
