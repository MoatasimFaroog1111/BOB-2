"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { API_BASE_URL } from "@/lib/api";

type PolicyRecord = {
  id: number;
  external_llm_enabled: boolean;
  approved_provider: string | null;
  approved_model: string | null;
  allowed_purposes: string[];
  allow_redacted_document_text: boolean;
  allow_financial_values: boolean;
  max_redacted_text_chars: number;
  dpa_version: string | null;
  dpa_reference: string | null;
  data_residency_region: string | null;
  provider_retention_mode: string | null;
  accepted_by_user_id: number | null;
  accepted_at: string | null;
  revoked_by_user_id: number | null;
  revoked_at: string | null;
  last_reviewed_at: string | null;
  policy_version: number;
  created_at: string;
  updated_at: string;
};

type PolicyResponse = {
  organization_id: number;
  global_enabled: boolean;
  api_key_configured: boolean;
  effective_enabled: boolean;
  required_dpa_version: string;
  globally_allowed_providers: string[];
  globally_allowed_models: string[];
  available_purposes: string[];
  available_retention_modes: string[];
  global_max_redacted_text_chars: number;
  policy: PolicyRecord | null;
};

type DisclosureEvent = {
  id: number;
  action: string;
  request_id: string | null;
  user_id: number | null;
  details: Record<string, unknown>;
  created_at: string;
};

type PolicyForm = {
  external_llm_enabled: boolean;
  approved_provider: string;
  approved_model: string;
  allowed_purposes: string[];
  allow_redacted_document_text: boolean;
  allow_financial_values: boolean;
  max_redacted_text_chars: number;
  dpa_version: string;
  dpa_reference: string;
  data_residency_region: string;
  provider_retention_mode: string;
  accept_dpa: boolean;
};

const EMPTY_FORM: PolicyForm = {
  external_llm_enabled: false,
  approved_provider: "",
  approved_model: "",
  allowed_purposes: [],
  allow_redacted_document_text: false,
  allow_financial_values: false,
  max_redacted_text_chars: 0,
  dpa_version: "",
  dpa_reference: "",
  data_residency_region: "",
  provider_retention_mode: "",
  accept_dpa: false,
};

async function readJson(response: Response) {
  return response.json().catch(() => null);
}

function formatDate(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("ar-SA");
}

function actionLabel(action: string) {
  const labels: Record<string, string> = {
    external_llm_disclosure_blocked: "تم الحظر قبل الإرسال",
    external_llm_disclosure_started: "بدأ إفصاح منقح",
    external_llm_disclosure_succeeded: "نجح الإفصاح",
    external_llm_disclosure_failed: "فشل مزود الذكاء الاصطناعي",
  };
  return labels[action] || action;
}

function policyToForm(response: PolicyResponse): PolicyForm {
  const policy = response.policy;
  const firstPair = response.globally_allowed_models[0] || "";
  const [, firstModel = ""] = firstPair.split(":", 2);
  if (!policy) {
    return {
      ...EMPTY_FORM,
      approved_provider: response.globally_allowed_providers[0] || "",
      approved_model: firstModel,
      dpa_version: response.required_dpa_version,
      provider_retention_mode: response.available_retention_modes[0] || "",
    };
  }
  return {
    external_llm_enabled: policy.external_llm_enabled,
    approved_provider: policy.approved_provider || "",
    approved_model: policy.approved_model || "",
    allowed_purposes: policy.allowed_purposes || [],
    allow_redacted_document_text: policy.allow_redacted_document_text,
    allow_financial_values: policy.allow_financial_values,
    max_redacted_text_chars: policy.max_redacted_text_chars,
    dpa_version: policy.dpa_version || response.required_dpa_version,
    dpa_reference: policy.dpa_reference || "",
    data_residency_region: policy.data_residency_region || "",
    provider_retention_mode:
      policy.provider_retention_mode || response.available_retention_modes[0] || "",
    accept_dpa: false,
  };
}

export default function ExternalLLMAdministrationPage() {
  const [policyState, setPolicyState] = useState<PolicyResponse | null>(null);
  const [disclosures, setDisclosures] = useState<DisclosureEvent[]>([]);
  const [form, setForm] = useState<PolicyForm>(EMPTY_FORM);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const loadAll = useCallback(async () => {
    setError("");
    try {
      const [policyResponse, disclosureResponse] = await Promise.all([
        fetch(`${API_BASE_URL}/api/v1/llm/policy`, { cache: "no-store" }),
        fetch(`${API_BASE_URL}/api/v1/llm/disclosures?limit=100`, { cache: "no-store" }),
      ]);
      const [policyBody, disclosureBody] = await Promise.all([
        readJson(policyResponse),
        readJson(disclosureResponse),
      ]);
      if (!policyResponse.ok) {
        throw new Error(policyBody?.detail || "تعذر قراءة سياسة الذكاء الاصطناعي الخارجي.");
      }
      if (!disclosureResponse.ok) {
        throw new Error(disclosureBody?.detail || "تعذر قراءة سجل الإفصاحات.");
      }
      const typedPolicy = policyBody as PolicyResponse;
      setPolicyState(typedPolicy);
      setDisclosures(disclosureBody as DisclosureEvent[]);
      setForm(policyToForm(typedPolicy));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "تعذر تحميل إعدادات الذكاء الاصطناعي.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const approvedModelOptions = useMemo(() => {
    if (!policyState) return [];
    return policyState.globally_allowed_models
      .map((pair) => {
        const [provider, ...modelParts] = pair.split(":");
        return { provider, model: modelParts.join(":") };
      })
      .filter((item) => item.provider === form.approved_provider && item.model);
  }, [form.approved_provider, policyState]);

  const setPurpose = (purpose: string, enabled: boolean) => {
    setForm((current) => ({
      ...current,
      allowed_purposes: enabled
        ? Array.from(new Set([...current.allowed_purposes, purpose]))
        : current.allowed_purposes.filter((item) => item !== purpose),
    }));
  };

  const savePolicy = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");
    try {
      if (form.external_llm_enabled && !form.accept_dpa) {
        throw new Error("يجب تأكيد قبول اتفاقية معالجة البيانات عند التفعيل أو التغيير الجوهري.");
      }
      const payload = {
        ...form,
        max_redacted_text_chars: form.allow_redacted_document_text
          ? form.max_redacted_text_chars
          : 0,
      };
      const response = await fetch(`${API_BASE_URL}/api/v1/llm/policy`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await readJson(response);
      if (!response.ok) {
        throw new Error(body?.detail || "تعذر حفظ سياسة الذكاء الاصطناعي الخارجي.");
      }
      setMessage(
        payload.external_llm_enabled
          ? "تم حفظ الموافقة المؤسسية. لا يصبح الاتصال فعالًا إلا إذا كانت البوابة العالمية والمفتاح التقني مفعّلين أيضًا."
          : "تم تعطيل المعالجة الخارجية وتسجيل الإلغاء في سجل التدقيق.",
      );
      await loadAll();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "تعذر حفظ السياسة.");
    } finally {
      setSaving(false);
    }
  };

  const disablePolicy = async () => {
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/llm/policy`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          external_llm_enabled: false,
          accept_dpa: false,
          max_redacted_text_chars: form.allow_redacted_document_text
            ? form.max_redacted_text_chars
            : 0,
        }),
      });
      const body = await readJson(response);
      if (!response.ok) {
        throw new Error(body?.detail || "تعذر تعطيل المعالجة الخارجية.");
      }
      setMessage("تم تعطيل المعالجة الخارجية وإلغاء الموافقة الحالية.");
      await loadAll();
    } catch (disableError) {
      setError(disableError instanceof Error ? disableError.message : "تعذر تعطيل السياسة.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <main className="min-h-screen bg-slate-950 p-8 text-slate-100">جارٍ تحميل السياسة…</main>;
  }

  return (
    <main className="min-h-screen bg-slate-950 p-6 text-slate-100 md:p-10" dir="rtl">
      <div className="mx-auto max-w-7xl space-y-8">
        <header className="flex flex-col gap-4 border-b border-slate-800 pb-6 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="mb-2 text-sm font-semibold text-cyan-400">حماية الإفصاح عن البيانات</p>
            <h1 className="text-3xl font-bold">إدارة الذكاء الاصطناعي الخارجي</h1>
            <p className="mt-3 max-w-3xl text-sm leading-7 text-slate-400">
              وجود مفتاح API لا يعتبر موافقة. يلزم تفعيل عالمي منفصل، وموافقة مؤسسية موثقة،
              واتفاقية معالجة بيانات حالية، ومزود ونموذج وغرض محدد، وتنقيح قبل كل إرسال.
            </p>
          </div>
          <Link href="/admin/telegram" className="text-sm text-cyan-300 hover:text-cyan-200">
            إدارة Telegram ←
          </Link>
        </header>

        {error ? <div className="rounded-xl border border-red-700 bg-red-950/40 p-4 text-red-200">{error}</div> : null}
        {message ? <div className="rounded-xl border border-emerald-700 bg-emerald-950/40 p-4 text-emerald-200">{message}</div> : null}

        <section className="grid gap-4 md:grid-cols-4">
          <StatusCard
            title="البوابة العالمية"
            value={policyState?.global_enabled ? "مفعّلة" : "معطلة"}
            safe={!policyState?.global_enabled}
            note="تحتاج تغييرًا صريحًا في بيئة النشر."
          />
          <StatusCard
            title="موافقة المؤسسة"
            value={policyState?.policy?.external_llm_enabled ? "مفعّلة" : "معطلة"}
            safe={!policyState?.policy?.external_llm_enabled}
            note={`الإصدار ${policyState?.policy?.policy_version || 0}`}
          />
          <StatusCard
            title="المفتاح التقني"
            value={policyState?.api_key_configured ? "موجود" : "غير موجود"}
            safe={!policyState?.api_key_configured}
            note="لا يتم عرض المفتاح أو جزء منه."
          />
          <StatusCard
            title="الحالة الفعلية"
            value={policyState?.effective_enabled ? "يسمح بالإرسال" : "Fail-closed"}
            safe={!policyState?.effective_enabled}
            note="يجب نجاح جميع البوابات معًا."
          />
        </section>

        <form onSubmit={savePolicy} className="space-y-6 rounded-2xl border border-slate-800 bg-slate-900/60 p-6">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-xl font-semibold">سياسة المؤسسة</h2>
              <p className="mt-1 text-sm text-slate-400">المؤسسة رقم {policyState?.organization_id}</p>
            </div>
            <label className="flex items-center gap-3 rounded-xl border border-slate-700 px-4 py-3">
              <input
                type="checkbox"
                checked={form.external_llm_enabled}
                onChange={(event) =>
                  setForm((current) => ({ ...current, external_llm_enabled: event.target.checked }))
                }
              />
              <span>طلب تفعيل المعالجة الخارجية لهذه المؤسسة</span>
            </label>
          </div>

          <div className="grid gap-5 md:grid-cols-2">
            <Field label="المزود المعتمد">
              <select
                value={form.approved_provider}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    approved_provider: event.target.value,
                    approved_model: "",
                  }))
                }
                className="input"
              >
                <option value="">اختر المزود</option>
                {policyState?.globally_allowed_providers.map((provider) => (
                  <option key={provider} value={provider}>{provider}</option>
                ))}
              </select>
            </Field>
            <Field label="النموذج المعتمد">
              <select
                value={form.approved_model}
                onChange={(event) =>
                  setForm((current) => ({ ...current, approved_model: event.target.value }))
                }
                className="input"
              >
                <option value="">اختر النموذج</option>
                {approvedModelOptions.map((item) => (
                  <option key={`${item.provider}:${item.model}`} value={item.model}>{item.model}</option>
                ))}
              </select>
            </Field>
          </div>

          <div>
            <h3 className="mb-3 font-semibold">الأغراض المسموح بها</h3>
            <div className="grid gap-3 md:grid-cols-3">
              {policyState?.available_purposes.map((purpose) => (
                <label key={purpose} className="flex items-center gap-3 rounded-xl border border-slate-700 p-3 text-sm">
                  <input
                    type="checkbox"
                    checked={form.allowed_purposes.includes(purpose)}
                    onChange={(event) => setPurpose(purpose, event.target.checked)}
                  />
                  <span>{purpose}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <label className="rounded-xl border border-amber-800 bg-amber-950/20 p-4">
              <span className="flex items-center gap-3 font-semibold">
                <input
                  type="checkbox"
                  checked={form.allow_redacted_document_text}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      allow_redacted_document_text: event.target.checked,
                      max_redacted_text_chars: event.target.checked
                        ? Math.min(1000, policyState?.global_max_redacted_text_chars || 0)
                        : 0,
                    }))
                  }
                />
                السماح بنص مستند منقح فقط
              </span>
              <p className="mt-2 text-xs leading-6 text-amber-200/80">
                يبقى النص الخام محليًا. تُحذف الأسماء والعناوين والمعرفات والمراجع قبل الإرسال،
                لكن التنقيح الآلي لا يغني عن تقييم قانوني للبيانات.
              </p>
            </label>
            <label className="rounded-xl border border-red-900 bg-red-950/20 p-4">
              <span className="flex items-center gap-3 font-semibold">
                <input
                  type="checkbox"
                  checked={form.allow_financial_values}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, allow_financial_values: event.target.checked }))
                  }
                />
                السماح بالقيم المالية
              </span>
              <p className="mt-2 text-xs leading-6 text-red-200/80">
                عند إيقافها تُحذف المبالغ والأرصدة والمدين والدائن والتكلفة من البيانات المنظمة والنص المنقح.
              </p>
            </label>
          </div>

          {form.allow_redacted_document_text ? (
            <Field label={`الحد الأقصى للنص المنقح — السقف العالمي ${policyState?.global_max_redacted_text_chars || 0}`}>
              <input
                type="number"
                min={0}
                max={policyState?.global_max_redacted_text_chars || 0}
                value={form.max_redacted_text_chars}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    max_redacted_text_chars: Number(event.target.value) || 0,
                  }))
                }
                className="input"
              />
            </Field>
          ) : null}

          <div className="grid gap-5 md:grid-cols-2">
            <Field label="إصدار اتفاقية معالجة البيانات المطلوبة">
              <input
                value={form.dpa_version}
                onChange={(event) => setForm((current) => ({ ...current, dpa_version: event.target.value }))}
                className="input"
                readOnly
              />
            </Field>
            <Field label="مرجع الاتفاقية أو قرار الموافقة">
              <input
                value={form.dpa_reference}
                onChange={(event) => setForm((current) => ({ ...current, dpa_reference: event.target.value }))}
                placeholder="مثال: DPA-2026-LEGAL-001"
                className="input"
              />
            </Field>
            <Field label="منطقة إقامة البيانات المتفق عليها">
              <input
                value={form.data_residency_region}
                onChange={(event) => setForm((current) => ({ ...current, data_residency_region: event.target.value }))}
                placeholder="مثال: KSA أو EU"
                className="input"
              />
            </Field>
            <Field label="وضع احتفاظ المزود">
              <select
                value={form.provider_retention_mode}
                onChange={(event) =>
                  setForm((current) => ({ ...current, provider_retention_mode: event.target.value }))
                }
                className="input"
              >
                <option value="">اختر وضع الاحتفاظ</option>
                {policyState?.available_retention_modes.map((mode) => (
                  <option key={mode} value={mode}>{mode}</option>
                ))}
              </select>
            </Field>
          </div>

          <label className="flex items-start gap-3 rounded-xl border border-cyan-800 bg-cyan-950/20 p-4">
            <input
              type="checkbox"
              checked={form.accept_dpa}
              onChange={(event) => setForm((current) => ({ ...current, accept_dpa: event.target.checked }))}
              className="mt-1"
            />
            <span className="text-sm leading-7 text-cyan-100">
              أؤكد أنني مخول من المؤسسة، وأن المرجع أعلاه يمثل اتفاقية/مراجعة قانونية حقيقية وسارية
              للمزود والنموذج والأغراض المحددة. هذا التأكيد يُسجل باسم مستخدم النظام ووقته.
            </span>
          </label>

          <div className="flex flex-wrap gap-3">
            <button
              type="submit"
              disabled={saving}
              className="rounded-xl bg-cyan-600 px-5 py-3 font-semibold text-white hover:bg-cyan-500 disabled:opacity-50"
            >
              {saving ? "جارٍ الحفظ…" : "حفظ السياسة"}
            </button>
            {policyState?.policy?.external_llm_enabled ? (
              <button
                type="button"
                disabled={saving}
                onClick={() => void disablePolicy()}
                className="rounded-xl border border-red-700 px-5 py-3 font-semibold text-red-200 hover:bg-red-950/40 disabled:opacity-50"
              >
                تعطيل وإلغاء الموافقة
              </button>
            ) : null}
          </div>
        </form>

        <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6">
          <div className="mb-5 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
            <div>
              <h2 className="text-xl font-semibold">سجل الإفصاحات الآمن</h2>
              <p className="mt-1 text-sm text-slate-400">
                لا يحتوي على النص أو Prompt أو رد المزود؛ يعرض Hash والأحجام وفئات التنقيح والحالة فقط.
              </p>
            </div>
            <button type="button" onClick={() => void loadAll()} className="text-sm text-cyan-300 hover:text-cyan-200">
              تحديث
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-800 text-sm">
              <thead className="text-right text-slate-400">
                <tr>
                  <th className="px-3 py-3">الوقت</th>
                  <th className="px-3 py-3">الحالة</th>
                  <th className="px-3 py-3">Request ID</th>
                  <th className="px-3 py-3">المستخدم</th>
                  <th className="px-3 py-3">بيانات التدقيق غير الحساسة</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {disclosures.map((event) => (
                  <tr key={event.id} className="align-top">
                    <td className="whitespace-nowrap px-3 py-4 text-slate-300">{formatDate(event.created_at)}</td>
                    <td className="whitespace-nowrap px-3 py-4 font-medium">{actionLabel(event.action)}</td>
                    <td className="px-3 py-4 font-mono text-xs text-slate-400">{event.request_id || "—"}</td>
                    <td className="px-3 py-4">{event.user_id || "—"}</td>
                    <td className="max-w-xl px-3 py-4">
                      <pre className="whitespace-pre-wrap break-all rounded-lg bg-slate-950 p-3 text-xs text-slate-300">
                        {JSON.stringify(event.details, null, 2)}
                      </pre>
                    </td>
                  </tr>
                ))}
                {!disclosures.length ? (
                  <tr><td colSpan={5} className="px-3 py-8 text-center text-slate-500">لا توجد إفصاحات خارجية مسجلة.</td></tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      </div>
      <style jsx>{`
        .input {
          width: 100%;
          border-radius: 0.75rem;
          border: 1px solid rgb(51 65 85);
          background: rgb(2 6 23);
          padding: 0.75rem 0.875rem;
          color: rgb(241 245 249);
          outline: none;
        }
        .input:focus {
          border-color: rgb(6 182 212);
          box-shadow: 0 0 0 1px rgb(6 182 212);
        }
      `}</style>
    </main>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-2">
      <span className="text-sm font-medium text-slate-300">{label}</span>
      {children}
    </label>
  );
}

function StatusCard({
  title,
  value,
  safe,
  note,
}: {
  title: string;
  value: string;
  safe: boolean;
  note: string;
}) {
  return (
    <article className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <p className="text-sm text-slate-400">{title}</p>
      <p className={`mt-2 text-xl font-bold ${safe ? "text-emerald-300" : "text-amber-300"}`}>{value}</p>
      <p className="mt-2 text-xs leading-5 text-slate-500">{note}</p>
    </article>
  );
}
