"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

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
  requested_by?: string;
};

export default function TelegramAdministrationPage() {
  const [status, setStatus] = useState<TelegramRuntimeStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [disabling, setDisabling] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const loadStatus = useCallback(async () => {
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/telegram/runtime-status`, {
        cache: "no-store",
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(body?.detail || "تعذر قراءة حالة Telegram Bot.");
      }
      setStatus(body as TelegramRuntimeStatus);
    } catch (statusError) {
      setError(
        statusError instanceof Error
          ? statusError.message
          : "تعذر قراءة حالة Telegram Bot.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadStatus();
    const timer = window.setInterval(() => void loadStatus(), 10_000);
    return () => window.clearInterval(timer);
  }, [loadStatus]);

  const emergencyDisable = async () => {
    setDisabling(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/telegram/emergency-disable`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(body?.detail || "تعذر تنفيذ الإيقاف الطارئ.");
      }
      setStatus(body as TelegramRuntimeStatus);
      setMessage("تم إيقاف Telegram Bot ومسح جميع العمليات المعلقة فورًا.");
    } catch (disableError) {
      setError(
        disableError instanceof Error
          ? disableError.message
          : "تعذر تنفيذ الإيقاف الطارئ.",
      );
    } finally {
      setDisabling(false);
    }
  };

  const yesNo = (value: boolean) => (value ? "نعم" : "لا");

  return (
    <main className="min-h-screen bg-slate-950 px-5 py-8 text-white">
      <div className="mx-auto max-w-4xl space-y-6">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <Link href="/erp" className="text-sm text-amber-300 hover:underline">
              العودة إلى إعدادات ERP
            </Link>
            <h1 className="mt-2 text-3xl font-bold">إدارة Telegram Bot الأمنية</h1>
            <p className="mt-2 text-sm text-white/60">
              تعرض هذه الصفحة حالة التشغيل فقط، ولا تعرض رمز البوت أو أي سر مشفّر.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void loadStatus()}
            disabled={loading}
            className="rounded-lg border border-white/15 bg-white/5 px-4 py-2 text-sm hover:bg-white/10 disabled:opacity-50"
          >
            تحديث الحالة
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
          {loading && !status ? (
            <p className="text-white/60">جاري تحميل الحالة…</p>
          ) : status ? (
            <div className="space-y-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-widest text-white/45">الحالة الفعلية</p>
                  <p className={`mt-1 text-2xl font-bold ${status.running ? "text-green-400" : "text-red-300"}`}>
                    {status.running ? "يعمل" : "متوقف"}
                  </p>
                </div>
                <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-white/70">
                  البيئة: {status.environment}
                </span>
              </div>

              <dl className="grid gap-3 sm:grid-cols-2">
                <StatusRow label="مفعّل في الإعدادات" value={yesNo(status.enabled_by_configuration)} />
                <StatusRow label="جاهز أمنيًا للإنتاج" value={yesNo(status.production_ready)} />
                <StatusRow label="الإيقاف الطارئ مفعّل" value={yesNo(status.emergency_disabled)} />
                <StatusRow label="سياسة التشغيل تسمح" value={yesNo(status.runtime_allowed)} />
                <StatusRow label="رمز البوت محفوظ" value={yesNo(status.token_configured)} />
                <StatusRow label="العمليات المعلقة" value={String(status.pending_entries)} />
                <StatusRow label="سبب السياسة" value={status.policy_reason} />
                <StatusRow label="آخر سبب تشغيل" value={status.last_runtime_reason} />
              </dl>

              <div className="rounded-xl border border-red-500/25 bg-red-950/20 p-4">
                <h2 className="font-semibold text-red-200">الإيقاف الطارئ</h2>
                <p className="mt-1 text-sm text-white/55">
                  يوقف الـPolling فورًا، ويمنع أي تشغيل جديد داخل العملية الحالية، ويمسح جميع الموافقات والعمليات المعلقة في الذاكرة.
                </p>
                <button
                  type="button"
                  onClick={emergencyDisable}
                  disabled={disabling || status.emergency_disabled}
                  className="mt-4 rounded-lg bg-red-500 px-4 py-2 font-semibold text-white hover:bg-red-400 disabled:cursor-not-allowed disabled:opacity-45"
                >
                  {disabling ? "جاري الإيقاف…" : status.emergency_disabled ? "تم الإيقاف الطارئ" : "إيقاف Telegram Bot فورًا"}
                </button>
              </div>
            </div>
          ) : null}
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
