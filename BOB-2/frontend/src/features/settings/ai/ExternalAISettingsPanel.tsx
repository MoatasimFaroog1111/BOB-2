"use client";

import type { ReactNode } from "react";

import { useExternalAISettings } from "./useExternalAISettings";

function StatusCard({
  title,
  value,
  note,
  healthy,
}: {
  title: string;
  value: string;
  note: string;
  healthy: boolean;
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/30 p-4">
      <p className="text-xs text-white/50">{title}</p>
      <p className={`mt-2 text-lg font-semibold ${healthy ? "text-emerald-400" : "text-amber-400"}`}>
        {value}
      </p>
      <p className="mt-2 text-xs leading-5 text-white/45">{note}</p>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="space-y-2 text-sm text-white/75">
      <span className="block font-medium">{label}</span>
      {children}
    </label>
  );
}

const inputClass =
  "w-full rounded-xl border border-white/15 bg-black/35 px-3 py-2.5 text-sm text-white outline-none transition focus:border-amber-400/70";

export function ExternalAISettingsPanel() {
  const {
    settings,
    form,
    setForm,
    apiKey,
    setApiKey,
    loading,
    saving,
    error,
    message,
    modelOptions,
    saveCredential,
    revokeCredential,
    savePolicy,
  } = useExternalAISettings();

  if (loading) {
    return <div className="p-6 text-sm text-white/60">جارٍ تحميل إعدادات الذكاء الاصطناعي…</div>;
  }

  return (
    <div className="space-y-6 p-6" dir="rtl">
      <div>
        <p className="text-xs font-semibold tracking-wider text-amber-400">AI CONNECTION</p>
        <h1 className="mt-1 text-2xl font-bold text-white">الاتصال بنموذج الذكاء الاصطناعي</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-white/55">
          اختر المزود والنموذج، خزّن مفتاح API بأمان، وحدد نطاق البيانات المسموح بإرسالها. لا يظهر المفتاح مرة أخرى بعد حفظه.
        </p>
      </div>

      {error ? (
        <div className="rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-200">{error}</div>
      ) : null}
      {message ? (
        <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-4 text-sm text-emerald-200">{message}</div>
      ) : null}

      <section className="grid gap-4 md:grid-cols-4">
        <StatusCard
          title="مفتاح الاتصال"
          value={settings?.api_key_configured ? "محفوظ" : "غير محفوظ"}
          healthy={Boolean(settings?.api_key_configured)}
          note={settings?.credential?.last_rotated_at ? `آخر تدوير: ${new Date(settings.credential.last_rotated_at).toLocaleString("ar-SA")}` : "يُحفظ في مخزن الأسرار المركزي."}
        />
        <StatusCard
          title="سياسة المؤسسة"
          value={settings?.policy?.external_llm_enabled ? "مفعّلة" : "معطلة"}
          healthy={Boolean(settings?.policy?.external_llm_enabled)}
          note={`إصدار السياسة: ${settings?.policy?.policy_version || 0}`}
        />
        <StatusCard
          title="بوابة النشر"
          value={settings?.global_enabled ? "مفعّلة" : "معطلة"}
          healthy={Boolean(settings?.global_enabled)}
          note="مفتاح أمان عام يبقى تحت تحكم بيئة النشر."
        />
        <StatusCard
          title="الحالة الفعلية"
          value={settings?.effective_enabled ? "جاهز للاتصال" : "مغلق آمنًا"}
          healthy={Boolean(settings?.effective_enabled)}
          note="لا يتم الاتصال إلا عند نجاح جميع طبقات الحماية."
        />
      </section>

      <section className="rounded-2xl border border-white/10 bg-black/30 p-5">
        <div className="flex flex-col gap-4 md:flex-row md:items-end">
          <div className="flex-1">
            <Field label={settings?.api_key_configured ? "تدوير مفتاح API" : "مفتاح API"}>
              <input
                type="password"
                autoComplete="new-password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder="ألصق المفتاح هنا؛ لن يُعرض بعد الحفظ"
                className={inputClass}
              />
            </Field>
          </div>
          <button
            type="button"
            disabled={saving || apiKey.trim().length < 20}
            onClick={() => void saveCredential()}
            className="rounded-xl bg-amber-500 px-5 py-2.5 text-sm font-semibold text-black disabled:cursor-not-allowed disabled:opacity-40"
          >
            {saving ? "جارٍ الحفظ…" : settings?.api_key_configured ? "تدوير المفتاح" : "حفظ المفتاح"}
          </button>
          {settings?.api_key_configured ? (
            <button
              type="button"
              disabled={saving}
              onClick={() => void revokeCredential()}
              className="rounded-xl border border-red-500/40 px-5 py-2.5 text-sm font-medium text-red-300 disabled:opacity-40"
            >
              إلغاء المفتاح
            </button>
          ) : null}
        </div>
        {settings?.credential?.version_fingerprint ? (
          <p className="mt-3 text-xs text-white/45">بصمة الإصدار: {settings.credential.version_fingerprint}</p>
        ) : null}
      </section>

      <section className="space-y-5 rounded-2xl border border-white/10 bg-black/30 p-5">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-white">المزود وسياسة الاستخدام</h2>
            <p className="mt-1 text-xs text-white/45">المؤسسة رقم {settings?.organization_id}</p>
          </div>
          <label className="flex items-center gap-3 rounded-xl border border-white/10 px-4 py-3 text-sm text-white/75">
            <input
              type="checkbox"
              checked={form.external_llm_enabled}
              onChange={(event) =>
                setForm((current) => ({ ...current, external_llm_enabled: event.target.checked }))
              }
            />
            تفعيل الاتصال لهذه المؤسسة
          </label>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <Field label="المزود">
            <select
              value={form.approved_provider}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  approved_provider: event.target.value,
                  approved_model: "",
                }))
              }
              className={inputClass}
            >
              <option value="">اختر المزود</option>
              {settings?.globally_allowed_providers.map((provider) => (
                <option key={provider} value={provider}>{provider}</option>
              ))}
            </select>
          </Field>
          <Field label="النموذج">
            <select
              value={form.approved_model}
              onChange={(event) =>
                setForm((current) => ({ ...current, approved_model: event.target.value }))
              }
              className={inputClass}
            >
              <option value="">اختر النموذج</option>
              {modelOptions.map((model) => (
                <option key={model} value={model}>{model}</option>
              ))}
            </select>
          </Field>
          <Field label="مرجع اتفاقية معالجة البيانات">
            <input
              value={form.dpa_reference}
              onChange={(event) => setForm((current) => ({ ...current, dpa_reference: event.target.value }))}
              placeholder="رقم العقد أو رابط المرجع الداخلي"
              className={inputClass}
            />
          </Field>
          <Field label="منطقة إقامة البيانات">
            <input
              value={form.data_residency_region}
              onChange={(event) => setForm((current) => ({ ...current, data_residency_region: event.target.value }))}
              placeholder="مثال: KSA / EU / Global"
              className={inputClass}
            />
          </Field>
          <Field label="وضع الاحتفاظ لدى المزود">
            <select
              value={form.provider_retention_mode}
              onChange={(event) => setForm((current) => ({ ...current, provider_retention_mode: event.target.value }))}
              className={inputClass}
            >
              <option value="">اختر سياسة الاحتفاظ</option>
              {settings?.available_retention_modes.map((mode) => (
                <option key={mode} value={mode}>{mode}</option>
              ))}
            </select>
          </Field>
          <Field label="الحد الأقصى للنص المنقح">
            <input
              type="number"
              min={0}
              max={settings?.global_max_redacted_text_chars || 0}
              disabled={!form.allow_redacted_document_text}
              value={form.max_redacted_text_chars}
              onChange={(event) =>
                setForm((current) => ({ ...current, max_redacted_text_chars: Number(event.target.value) || 0 }))
              }
              className={inputClass}
            />
          </Field>
        </div>

        <div>
          <p className="mb-3 text-sm font-medium text-white/75">الأغراض المسموحة</p>
          <div className="grid gap-2 md:grid-cols-2">
            {settings?.available_purposes.map((purpose) => (
              <label key={purpose} className="flex items-center gap-3 rounded-xl border border-white/10 px-3 py-2 text-sm text-white/65">
                <input
                  type="checkbox"
                  checked={form.allowed_purposes.includes(purpose)}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      allowed_purposes: event.target.checked
                        ? Array.from(new Set([...current.allowed_purposes, purpose]))
                        : current.allowed_purposes.filter((item) => item !== purpose),
                    }))
                  }
                />
                {purpose}
              </label>
            ))}
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <label className="flex items-center gap-3 rounded-xl border border-white/10 p-3 text-sm text-white/70">
            <input
              type="checkbox"
              checked={form.allow_redacted_document_text}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  allow_redacted_document_text: event.target.checked,
                  max_redacted_text_chars: event.target.checked ? current.max_redacted_text_chars : 0,
                }))
              }
            />
            السماح بإرسال نص مستند منقح
          </label>
          <label className="flex items-center gap-3 rounded-xl border border-white/10 p-3 text-sm text-white/70">
            <input
              type="checkbox"
              checked={form.allow_financial_values}
              onChange={(event) => setForm((current) => ({ ...current, allow_financial_values: event.target.checked }))}
            />
            السماح بالقيم المالية بعد التنقيح
          </label>
        </div>

        <label className="flex items-start gap-3 rounded-xl border border-amber-500/25 bg-amber-500/5 p-4 text-sm text-white/70">
          <input
            type="checkbox"
            checked={form.accept_dpa}
            onChange={(event) => setForm((current) => ({ ...current, accept_dpa: event.target.checked }))}
            className="mt-1"
          />
          <span>
            أؤكد قبول اتفاقية معالجة البيانات بالإصدار <strong>{form.dpa_version || settings?.required_dpa_version}</strong> وأن اختيار المزود والنموذج مصرح به للمؤسسة.
          </span>
        </label>

        <div className="flex justify-end">
          <button
            type="button"
            disabled={saving}
            onClick={() => void savePolicy()}
            className="rounded-xl bg-amber-500 px-6 py-2.5 text-sm font-semibold text-black disabled:opacity-40"
          >
            {saving ? "جارٍ الحفظ…" : "حفظ إعدادات الذكاء الاصطناعي"}
          </button>
        </div>
      </section>
    </div>
  );
}
