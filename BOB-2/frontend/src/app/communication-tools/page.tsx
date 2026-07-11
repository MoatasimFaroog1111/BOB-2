"use client";

import { useEffect, useMemo, useState } from "react";
import { API_BASE_URL } from "@/lib/api";
import { useLanguage } from "@/lib/LanguageContext";

type TelegramStatus = {
  configured: boolean;
  masked_token?: string;
  storage?: string;
};

type ActionKey = "current" | "telegram" | "logs";

export default function CommunicationToolsPage() {
  const { language } = useLanguage();
  const isArabic = language === "ar";
  const [activeAction, setActiveAction] = useState<ActionKey>("current");
  const [telegramToken, setTelegramToken] = useState("");
  const [status, setStatus] = useState<TelegramStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const labels = useMemo(
    () => ({
      title: isArabic ? "أدوات الاتصال" : "Communication Tools",
      subtitle: isArabic
        ? "إدارة قنوات الاتصال وحفظ إعداداتها بحيث تستمر بعد قفل المتصفح أو انتهاء الجلسة."
        : "Manage communication channels and keep their settings after closing the browser or ending the session.",
      current: isArabic ? "العمليات الحالية" : "Current Operations",
      telegram: isArabic ? "إعداد تليغرام" : "Telegram Setup",
      logs: isArabic ? "سجل الاتصال" : "Communication Log",
      tokenTitle: isArabic ? "توكن تليغرام" : "Telegram Token",
      tokenDesc: isArabic
        ? "سيتم حفظ التوكن في الخادم بشكل مشفّر، لذلك لن تحتاج لإدخاله كل مرة."
        : "The token is saved encrypted on the backend, so you do not need to enter it every time.",
      tokenPlaceholder: isArabic ? "الصق توكن البوت من BotFather" : "Paste the bot token from BotFather",
      save: isArabic ? "حفظ التوكن" : "Save token",
      clear: isArabic ? "حذف التوكن" : "Clear token",
      saved: isArabic ? "محفوظ" : "Saved",
      notSaved: isArabic ? "غير محفوظ" : "Not saved",
      masked: isArabic ? "التوكن المحفوظ" : "Saved token",
      currentDesc: isArabic
        ? "هذه شاشة مختصرة لحالة أدوات الاتصال الحالية."
        : "This is a quick view of the current communication tool status.",
      logsDesc: isArabic
        ? "سيظهر هنا سجل عمليات الاتصال القادمة بعد ربط القنوات."
        : "Communication activity will appear here after channels are connected.",
      success: isArabic ? "تم حفظ توكن تليغرام بنجاح." : "Telegram token saved successfully.",
      cleared: isArabic ? "تم حذف توكن تليغرام." : "Telegram token cleared.",
      loadError: isArabic ? "تعذر قراءة حالة توكن تليغرام." : "Could not read Telegram token status.",
      saveError: isArabic ? "تعذر حفظ توكن تليغرام." : "Could not save Telegram token.",
    }),
    [isArabic]
  );

  async function loadStatus() {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/communication-tools/telegram-token/status`, {
        cache: "no-store",
      });
      if (!response.ok) throw new Error("status failed");
      const data = (await response.json()) as TelegramStatus;
      setStatus(data);
      setError("");
    } catch {
      setError(labels.loadError);
    }
  }

  async function saveToken() {
    setLoading(true);
    setMessage("");
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/communication-tools/telegram-token`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: telegramToken }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body?.detail || labels.saveError);
      }
      const data = (await response.json()) as TelegramStatus;
      setStatus(data);
      setTelegramToken("");
      setMessage(labels.success);
    } catch (err) {
      setError(err instanceof Error ? err.message : labels.saveError);
    } finally {
      setLoading(false);
    }
  }

  async function clearToken() {
    setLoading(true);
    setMessage("");
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/communication-tools/telegram-token`, {
        method: "DELETE",
      });
      if (!response.ok) throw new Error(labels.saveError);
      const data = (await response.json()) as TelegramStatus;
      setStatus(data);
      setMessage(labels.cleared);
    } catch (err) {
      setError(err instanceof Error ? err.message : labels.saveError);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadStatus();
  }, []);

  const actionButtons: { key: ActionKey; label: string; description: string }[] = [
    {
      key: "current",
      label: labels.current,
      description: isArabic ? "عرض حالة القنوات المحفوظة حاليًا" : "View saved channel status",
    },
    {
      key: "telegram",
      label: labels.telegram,
      description: isArabic ? "حفظ أو تحديث توكن البوت" : "Save or update the bot token",
    },
    {
      key: "logs",
      label: labels.logs,
      description: isArabic ? "مراجعة سجل الاتصال" : "Review communication history",
    },
  ];

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">{labels.title}</h1>
        <p className="text-sm text-gray-400 mt-1 max-w-3xl">{labels.subtitle}</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {actionButtons.map((button) => (
          <button
            key={button.key}
            type="button"
            onClick={() => setActiveAction(button.key)}
            className={`rounded-2xl border p-5 text-start transition-all ${
              activeAction === button.key
                ? "border-amber-500/40 bg-amber-500/15 text-amber-300"
                : "border-white/10 bg-black/30 text-white hover:bg-white/5"
            }`}
          >
            <div className="text-base font-semibold">{button.label}</div>
            <div className="mt-2 text-xs text-gray-400 leading-relaxed">{button.description}</div>
          </button>
        ))}
      </div>

      {activeAction === "current" && (
        <section className="rounded-2xl border border-white/10 bg-black/30 p-6 space-y-4">
          <h2 className="text-lg font-semibold text-white">{labels.current}</h2>
          <p className="text-sm text-gray-400">{labels.currentDesc}</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <div className="text-sm text-gray-400">Telegram</div>
              <div className="mt-2 text-lg font-semibold text-white">
                {status?.configured ? labels.saved : labels.notSaved}
              </div>
              {status?.masked_token && (
                <div className="mt-1 text-xs text-amber-300">
                  {labels.masked}: {status.masked_token}
                </div>
              )}
            </div>
          </div>
        </section>
      )}

      {activeAction === "telegram" && (
        <section className="rounded-2xl border border-white/10 bg-black/30 p-6 space-y-4">
          <div>
            <h2 className="text-lg font-semibold text-white">{labels.tokenTitle}</h2>
            <p className="text-sm text-gray-400 mt-1">{labels.tokenDesc}</p>
          </div>

          <div className="flex flex-col md:flex-row gap-3">
            <input
              type="password"
              value={telegramToken}
              onChange={(event) => setTelegramToken(event.target.value)}
              placeholder={labels.tokenPlaceholder}
              className="flex-1 rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-sm text-white outline-none placeholder:text-gray-500 focus:border-amber-500/50"
            />
            <button
              type="button"
              onClick={saveToken}
              disabled={loading || !telegramToken.trim()}
              className="rounded-xl border border-amber-500/30 bg-amber-500/15 px-5 py-3 text-sm font-semibold text-amber-300 transition hover:bg-amber-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {labels.save}
            </button>
            <button
              type="button"
              onClick={clearToken}
              disabled={loading || !status?.configured}
              className="rounded-xl border border-red-500/30 bg-red-500/10 px-5 py-3 text-sm font-semibold text-red-300 transition hover:bg-red-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {labels.clear}
            </button>
          </div>

          <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4 text-sm text-gray-300">
            {status?.configured ? labels.saved : labels.notSaved}
            {status?.masked_token ? ` — ${status.masked_token}` : ""}
          </div>
        </section>
      )}

      {activeAction === "logs" && (
        <section className="rounded-2xl border border-white/10 bg-black/30 p-6 space-y-3">
          <h2 className="text-lg font-semibold text-white">{labels.logs}</h2>
          <p className="text-sm text-gray-400">{labels.logsDesc}</p>
        </section>
      )}

      {message && <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm text-emerald-300">{message}</div>}
      {error && <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">{error}</div>}
    </div>
  );
}
