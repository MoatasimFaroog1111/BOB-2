"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { API_BASE_URL } from "@/lib/api";

type TelegramRuntimeStatus = {
  environment: string;
  enabled_by_configuration: boolean;
  production_ready: boolean;
  emergency_disabled: boolean;
  runtime_allowed: boolean;
  running: boolean;
  token_configured: boolean;
  pending_entries: number;
  policy_reason: string;
  last_runtime_reason: string;
  group_chats_globally_enabled: boolean;
  requested_by?: string;
};

type TelegramSystemUser = {
  id: number;
  email: string;
  full_name: string;
  role: string;
  permissions: string[];
};

type TelegramAuthorization = {
  id: number;
  telegram_user_id: number;
  telegram_chat_id: number;
  organization_id: number;
  system_user_id: number;
  system_user_email: string;
  system_user_name: string;
  system_user_role: string;
  created_by_user_id: number;
  allow_group_chats: boolean;
  effective_group_access: boolean;
  is_active: boolean;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
};

async function readJson(response: Response) {
  return response.json().catch(() => null);
}

export default function TelegramAdministrationPage() {
  const [runtime, setRuntime] = useState<TelegramRuntimeStatus | null>(null);
  const [authorizations, setAuthorizations] = useState<TelegramAuthorization[]>([]);
  const [systemUsers, setSystemUsers] = useState<TelegramSystemUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [disabling, setDisabling] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [telegramUserId, setTelegramUserId] = useState("");
  const [telegramChatId, setTelegramChatId] = useState("");
  const [systemUserId, setSystemUserId] = useState("");
  const [allowGroupChats, setAllowGroupChats] = useState(false);

  const loadAll = useCallback(async () => {
    setError("");
    try {
      const [runtimeResponse, authorizationsResponse, usersResponse] = await Promise.all([
        fetch(`${API_BASE_URL}/api/v1/telegram/runtime-status`, { cache: "no-store" }),
        fetch(`${API_BASE_URL}/api/v1/telegram/authorizations`, { cache: "no-store" }),
        fetch(`${API_BASE_URL}/api/v1/telegram/system-users`, { cache: "no-store" }),
      ]);
      const [runtimeBody, authorizationsBody, usersBody] = await Promise.all([
        readJson(runtimeResponse),
        readJson(authorizationsResponse),
        readJson(usersResponse),
      ]);
      if (!runtimeResponse.ok) {
        throw new Error(runtimeBody?.detail || "تعذر قراءة حالة Telegram Bot.");
      }
      if (!authorizationsResponse.ok) {
        throw new Error(authorizationsBody?.detail || "تعذر قراءة قائمة Telegram المسموح بها.");
      }
      if (!usersResponse.ok) {
        throw new Error(usersBody?.detail || "تعذر قراءة مستخدمي النظام.");
      }
      setRuntime(runtimeBody as TelegramRuntimeStatus);
      setAuthorizations(authorizationsBody as TelegramAuthorization[]);
      setSystemUsers(usersBody as TelegramSystemUser[]);
      setSystemUserId((current) => current || String((usersBody as TelegramSystemUser[])[0]?.id || ""));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "تعذر تحميل إعدادات Telegram.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAll();
    const timer = window.setInterval(() => void loadAll(), 15_000);
    return () => window.clearInterval(timer);
  }, [loadAll]);

  const validateInteger = (value: string, label: string, allowNegative = false) => {
    const parsed = Number(value.trim());
    if (!Number.isSafeInteger(parsed) || parsed === 0 || (!allowNegative && parsed < 1)) {
      throw new Error(`${label} غير صحيح.`);
    }
    return parsed;
  };

  const createAuthorization = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const userId = validateInteger(telegramUserId, "Telegram user ID");
      const chatId = validateInteger(telegramChatId, "Chat ID", true);
      const linkedUserId = validateInteger(systemUserId, "مستخدم النظام");
      if (chatId < 0 && !allowGroupChats) {
        throw new Error("Chat ID السالب يمثل مجموعة ويتطلب السماح الصريح بالمجموعات.");
      }
      const response = await fetch(`${API_BASE_URL}/api/v1/telegram/authorizations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          telegram_user_id: userId,
          telegram_chat_id: chatId,
          system_user_id: linkedUserId,
          allow_group_chats: allowGroupChats,
          is_active: true,
        }),
      });
      const body = await readJson(response);
      if (!response.ok) {
        throw new Error(body?.detail || "تعذر إضافة الهوية إلى القائمة المسموح بها.");
      }
      setTelegramUserId("");
      setTelegramChatId("");
      setAllowGroupChats(false);
      setMessage("تم ربط هوية Telegram بالمؤسسة ومستخدم النظام بنجاح.");
      await loadAll();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "تعذر حفظ الربط.");
    } finally {
      setSaving(false);
    }
  };

  const setAuthorizationActive = async (record: TelegramAuthorization, isActive: boolean) => {
    setError("");
    setMessage("");
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/v1/telegram/authorizations/${record.id}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_active: isActive }),
        },
      );
      const body = await readJson(response);
      if (!response.ok) {
        throw new Error(body?.detail || "تعذر تحديث حالة الهوية.");
      }
      setMessage(isActive ? "تم تفعيل الهوية." : "تم تعطيل الهوية ومسح عملياتها المعلقة.");
      await loadAll();
    } catch (updateError) {
      setError(updateError instanceof Error ? updateError.message : "تعذر تحديث الهوية.");
    }
  };

  const deactivateAuthorization = async (record: TelegramAuthorization) => {
    setError("");
    setMessage("");
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/v1/telegram/authorizations/${record.id}`,
        { method: "DELETE" },
      );
      const body = await readJson(response);
      if (!response.ok) {
        throw new Error(body?.detail || "تعذر إلغاء التصريح.");
      }
      setMessage("تم إلغاء التصريح مع الاحتفاظ بسجله لأغراض التدقيق.");
      await loadAll();
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "تعذر إلغاء التصريح.");
    }
  };

  const emergencyDisable = async () => {
    setDisabling(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/telegram/emergency-disable`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const body = await readJson(response);
      if (!response.ok) {
        throw new Error(body?.detail || "تعذر تنفيذ الإيقاف الطارئ.");
      }
      setRuntime(body as TelegramRuntimeStatus);
      setMessage("تم إيقاف Telegram Bot ومسح جميع العمليات المعلقة فورًا.");
    } catch (disableError) {
      setError(disableError instanceof Error ? disableError.message : "تعذر تنفيذ الإيقاف الطارئ.");
    } finally {
      setDisabling(false);
    }
  };

  const yesNo = (value: boolean) => (value ? "نعم" : "لا");

  return (
    <main className="min-h-screen bg-slate-950 px-5 py-8 text-white">
      <div className="mx-auto max-w-6xl space-y-6">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <Link href="/erp" className="text-sm text-amber-300 hover:underline">
              العودة إلى إعدادات ERP
            </Link>
            <h1 className="mt-2 text-3xl font-bold">إدارة Telegram Bot الأمنية</h1>
            <p className="mt-2 max-w-3xl text-sm text-white/60">
              لا تُقبل أي رسالة أو موافقة إلا بعد مطابقة Telegram user ID وChat ID مع المؤسسة ومستخدم نظام نشط، ثم قراءة صلاحياته الحالية من قاعدة البيانات.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void loadAll()}
            disabled={loading}
            className="rounded-lg border border-white/15 bg-white/5 px-4 py-2 text-sm hover:bg-white/10 disabled:opacity-50"
          >
            تحديث البيانات
          </button>
        </header>

        {error && (
          <div role="alert" className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-red-200">
            {error}
          </div>
        )}
        {message && (
          <div className="rounded-xl border border-green-500/30 bg-green-500/10 p-4 text-green-200">
            {message}
          </div>
        )}

        <section className="rounded-2xl border border-white/10 bg-black/30 p-6 shadow-2xl">
          {loading && !runtime ? (
            <p className="text-white/60">جاري تحميل الحالة…</p>
          ) : runtime ? (
            <div className="space-y-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-widest text-white/45">الحالة الفعلية</p>
                  <p className={`mt-1 text-2xl font-bold ${runtime.running ? "text-green-400" : "text-red-300"}`}>
                    {runtime.running ? "يعمل" : "متوقف"}
                  </p>
                </div>
                <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-white/70">
                  البيئة: {runtime.environment}
                </span>
              </div>

              <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <StatusRow label="مفعّل في الإعدادات" value={yesNo(runtime.enabled_by_configuration)} />
                <StatusRow label="جاهز أمنيًا للإنتاج" value={yesNo(runtime.production_ready)} />
                <StatusRow label="الإيقاف الطارئ" value={yesNo(runtime.emergency_disabled)} />
                <StatusRow label="سياسة التشغيل تسمح" value={yesNo(runtime.runtime_allowed)} />
                <StatusRow label="رمز البوت محفوظ" value={yesNo(runtime.token_configured)} />
                <StatusRow label="المجموعات مفعلة عالميًا" value={yesNo(runtime.group_chats_globally_enabled)} />
                <StatusRow label="العمليات المعلقة" value={String(runtime.pending_entries)} />
                <StatusRow label="سبب السياسة" value={runtime.policy_reason} />
                <StatusRow label="آخر سبب تشغيل" value={runtime.last_runtime_reason} />
              </dl>

              <div className="rounded-xl border border-red-500/25 bg-red-950/20 p-4">
                <h2 className="font-semibold text-red-200">الإيقاف الطارئ</h2>
                <p className="mt-1 text-sm text-white/55">
                  يوقف الـPolling فورًا ويمنع التشغيل الجديد ويمسح جميع العمليات المعلقة.
                </p>
                <button
                  type="button"
                  onClick={emergencyDisable}
                  disabled={disabling || runtime.emergency_disabled}
                  className="mt-4 rounded-lg bg-red-500 px-4 py-2 font-semibold text-white hover:bg-red-400 disabled:cursor-not-allowed disabled:opacity-45"
                >
                  {disabling ? "جاري الإيقاف…" : runtime.emergency_disabled ? "تم الإيقاف الطارئ" : "إيقاف Telegram Bot فورًا"}
                </button>
              </div>
            </div>
          ) : null}
        </section>

        <section className="grid gap-6 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.4fr)]">
          <form onSubmit={createAuthorization} className="h-fit rounded-2xl border border-white/10 bg-black/30 p-6">
            <h2 className="text-xl font-semibold">إضافة هوية إلى القائمة المسموح بها</h2>
            <p className="mt-2 text-sm text-white/55">
              الصلاحيات لا تُحفظ هنا؛ تُقرأ دائمًا من الدور الحالي لمستخدم النظام المرتبط.
            </p>
            <div className="mt-5 space-y-4">
              <Field label="Telegram user ID">
                <input
                  value={telegramUserId}
                  onChange={(event) => setTelegramUserId(event.target.value)}
                  inputMode="numeric"
                  required
                  className="w-full rounded-lg border border-white/15 bg-white/5 px-3 py-2 outline-none focus:border-amber-400"
                />
              </Field>
              <Field label="Chat ID">
                <input
                  value={telegramChatId}
                  onChange={(event) => setTelegramChatId(event.target.value)}
                  inputMode="numeric"
                  required
                  className="w-full rounded-lg border border-white/15 bg-white/5 px-3 py-2 outline-none focus:border-amber-400"
                />
              </Field>
              <Field label="مستخدم النظام المرتبط">
                <select
                  value={systemUserId}
                  onChange={(event) => setSystemUserId(event.target.value)}
                  required
                  className="w-full rounded-lg border border-white/15 bg-slate-900 px-3 py-2 outline-none focus:border-amber-400"
                >
                  <option value="">اختر مستخدمًا نشطًا</option>
                  {systemUsers.map((user) => (
                    <option key={user.id} value={user.id}>
                      {user.full_name} — {user.email} — {user.role}
                    </option>
                  ))}
                </select>
              </Field>
              <label className="flex items-start gap-3 rounded-lg border border-white/10 bg-white/5 p-3 text-sm">
                <input
                  type="checkbox"
                  checked={allowGroupChats}
                  onChange={(event) => setAllowGroupChats(event.target.checked)}
                  disabled={!runtime?.group_chats_globally_enabled}
                  className="mt-1"
                />
                <span>
                  السماح لهذه الهوية داخل مجموعة أو Supergroup
                  {!runtime?.group_chats_globally_enabled && (
                    <span className="mt-1 block text-xs text-amber-300">المجموعات معطلة عالميًا حاليًا.</span>
                  )}
                </span>
              </label>
              <button
                type="submit"
                disabled={saving || !systemUsers.length}
                className="w-full rounded-lg bg-amber-400 px-4 py-2.5 font-semibold text-black hover:bg-amber-300 disabled:opacity-45"
              >
                {saving ? "جاري الحفظ…" : "إضافة التصريح"}
              </button>
            </div>
          </form>

          <div className="rounded-2xl border border-white/10 bg-black/30 p-6">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-xl font-semibold">الهويات المصرح بها</h2>
                <p className="mt-1 text-sm text-white/50">كل سجل مقيد بالمؤسسة الحالية فقط.</p>
              </div>
              <span className="rounded-full bg-white/5 px-3 py-1 text-xs text-white/65">
                {authorizations.length} سجل
              </span>
            </div>

            <div className="mt-5 space-y-3">
              {authorizations.length === 0 ? (
                <p className="rounded-xl border border-dashed border-white/15 p-6 text-center text-sm text-white/45">
                  لا توجد هويات Telegram مصرح بها.
                </p>
              ) : (
                authorizations.map((record) => (
                  <article key={record.id} className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="font-semibold">{record.system_user_name || record.system_user_email}</p>
                        <p className="text-xs text-white/50">{record.system_user_email} — {record.system_user_role}</p>
                      </div>
                      <span className={`rounded-full px-2.5 py-1 text-xs ${record.is_active ? "bg-green-500/15 text-green-300" : "bg-red-500/15 text-red-300"}`}>
                        {record.is_active ? "نشط" : "معطل"}
                      </span>
                    </div>
                    <dl className="mt-4 grid gap-2 text-sm sm:grid-cols-2">
                      <MiniRow label="Telegram user ID" value={String(record.telegram_user_id)} />
                      <MiniRow label="Chat ID" value={String(record.telegram_chat_id)} />
                      <MiniRow label="Organization ID" value={String(record.organization_id)} />
                      <MiniRow label="System user ID" value={String(record.system_user_id)} />
                      <MiniRow label="السماح بالمجموعة" value={yesNo(record.allow_group_chats)} />
                      <MiniRow label="السماح الفعلي بالمجموعة" value={yesNo(record.effective_group_access)} />
                      <MiniRow label="آخر استخدام" value={record.last_used_at ? new Date(record.last_used_at).toLocaleString("ar-SA") : "لم يستخدم"} />
                      <MiniRow label="تاريخ الإنشاء" value={new Date(record.created_at).toLocaleString("ar-SA")} />
                    </dl>
                    <div className="mt-4 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => void setAuthorizationActive(record, !record.is_active)}
                        className="rounded-lg border border-white/15 px-3 py-1.5 text-xs hover:bg-white/10"
                      >
                        {record.is_active ? "تعطيل مؤقت" : "إعادة التفعيل"}
                      </button>
                      <button
                        type="button"
                        onClick={() => void deactivateAuthorization(record)}
                        disabled={!record.is_active}
                        className="rounded-lg border border-red-500/30 px-3 py-1.5 text-xs text-red-300 hover:bg-red-500/10 disabled:opacity-35"
                      >
                        إلغاء التصريح
                      </button>
                    </div>
                  </article>
                ))
              )}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-3">
      <dt className="text-xs text-white/45">{label}</dt>
      <dd className="mt-1 break-words font-medium text-white/90">{value}</dd>
    </div>
  );
}

function MiniRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-black/20 px-3 py-2">
      <dt className="text-[11px] text-white/40">{label}</dt>
      <dd className="mt-0.5 break-all text-xs text-white/85">{value}</dd>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm text-white/70">{label}</span>
      {children}
    </label>
  );
}
