"use client";

import Link from "next/link";

import { SETTINGS_SECTIONS } from "@/features/settings/sections";
import { useLanguage } from "@/lib/LanguageContext";

export default function SettingsPage() {
  const { language, toggleLanguage } = useLanguage();
  const integrationSections = SETTINGS_SECTIONS.filter((section) => section.href !== "/settings");

  return (
    <div className="space-y-6 p-6">
      <div>
        <p className="text-xs font-semibold tracking-wider text-amber-400">SYSTEM SETTINGS</p>
        <h1 className="mt-1 text-2xl font-bold text-white">
          {language === "ar" ? "الضبط والتكاملات" : "Settings & Integrations"}
        </h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-white/55">
          {language === "ar"
            ? "إدارة إعدادات النظام واتصالات الذكاء الاصطناعي والأنظمة المحاسبية من مكان واحد."
            : "Manage system preferences, AI connections, and accounting-system integrations from one place."}
        </p>
      </div>

      <section className="rounded-2xl border border-white/10 bg-black/30 p-5">
        <h2 className="text-lg font-semibold text-white">
          {language === "ar" ? "اللغة" : "Language"}
        </h2>
        <div className="mt-4 flex flex-wrap items-center gap-4">
          <button
            type="button"
            onClick={toggleLanguage}
            className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm font-medium text-amber-300 transition hover:bg-amber-500/15"
          >
            {language === "ar" ? "Switch to English" : "التبديل إلى العربية"}
          </button>
          <span className="text-sm text-white/50">
            {language === "ar" ? "اللغة الحالية: العربية" : "Current language: English"}
          </span>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        {integrationSections.map((section) => (
          <Link
            key={section.href}
            href={section.href}
            className="group rounded-2xl border border-white/10 bg-black/30 p-5 transition hover:border-amber-500/35 hover:bg-amber-500/5"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs font-semibold tracking-wider text-amber-400">{section.badge}</p>
                <h2 className="mt-2 text-lg font-semibold text-white group-hover:text-amber-200">
                  {language === "ar" ? section.titleAr : section.titleEn}
                </h2>
                <p className="mt-2 text-sm leading-6 text-white/50">
                  {language === "ar" ? section.descriptionAr : section.descriptionEn}
                </p>
              </div>
              <span className="text-xl text-white/30 transition group-hover:text-amber-300">←</span>
            </div>
          </Link>
        ))}
      </section>

      <section className="rounded-2xl border border-white/10 bg-black/30 p-5 text-sm text-white/50">
        <p>GuardianAI Accountant &amp; Auditor Enterprise</p>
        <p className="mt-1">{language === "ar" ? "الإصدار: 1.0.0" : "Version: 1.0.0"}</p>
      </section>
    </div>
  );
}
