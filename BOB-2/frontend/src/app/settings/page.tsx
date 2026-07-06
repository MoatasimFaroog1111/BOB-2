"use client";

import { useLanguage } from "@/lib/LanguageContext";

export default function SettingsPage() {
  const { language, toggleLanguage, t } = useLanguage();

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">
          {language === "ar" ? "الإعدادات" : "Settings"}
        </h1>
        <p className="text-sm text-gray-400 mt-1">
          {language === "ar"
            ? "إعدادات النظام واللغة"
            : "System and language settings"}
        </p>
      </div>

      <div className="rounded-2xl border border-white/10 bg-black/30 p-6 space-y-4">
        <h2 className="text-lg font-semibold text-white">
          {language === "ar" ? "اللغة" : "Language"}
        </h2>
        <div className="flex items-center gap-4">
          <button
            onClick={toggleLanguage}
            className="px-4 py-2 rounded-xl bg-gradient-to-r from-amber-500/15 to-yellow-600/10 border border-amber-500/30 text-amber-400 text-sm font-medium hover:bg-amber-500/20 transition-colors"
          >
            {language === "ar" ? "Switch to English" : "التبديل إلى العربية"}
          </button>
          <span className="text-sm text-gray-400">
            {language === "ar" ? "اللغة الحالية: العربية" : "Current: English"}
          </span>
        </div>
      </div>

      <div className="rounded-2xl border border-white/10 bg-black/30 p-6 space-y-2">
        <h2 className="text-lg font-semibold text-white">
          {language === "ar" ? "معلومات النظام" : "System Info"}
        </h2>
        <div className="text-sm text-gray-400 space-y-1">
          <p>GuardianAI Accountant &amp; Auditor Enterprise</p>
          <p>{language === "ar" ? "الإصدار: 1.0.0" : "Version: 1.0.0"}</p>
        </div>
      </div>
    </div>
  );
}
