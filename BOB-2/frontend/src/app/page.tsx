"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { getBackendHealth } from "@/lib/api";
import { useLanguage } from "@/lib/LanguageContext";

type BackendState = "checking" | "healthy" | "unavailable";

const actions = [
  {
    href: "/bank-reconciliation",
    title: "Bank Reconciliation",
    titleAr: "المطابقة البنكية",
    description: "Upload, match, review, approve, and register safely.",
    descriptionAr: "ارفع الكشف، طابق، راجع، اعتمد وسجل بأمان.",
    badge: "Core",
  },
  {
    href: "/documents",
    title: "Documents",
    titleAr: "المستندات",
    description: "OCR, evidence extraction, and accounting review.",
    descriptionAr: "OCR واستخراج الأدلة والمراجعة المحاسبية.",
    badge: "Evidence",
  },
  {
    href: "/audit",
    title: "Audit Evidence",
    titleAr: "أدلة التدقيق",
    description: "Inspect the immutable audit trail and control evidence.",
    descriptionAr: "راجع سجل التدقيق المتسلسل وأدلة الرقابة.",
    badge: "Control",
  },
  {
    href: "/settings/accounting-systems",
    title: "Odoo Connection",
    titleAr: "ربط Odoo",
    description: "Review ERP connectivity and accounting-system settings.",
    descriptionAr: "راجع اتصال ERP وإعدادات النظام المحاسبي.",
    badge: "ERP",
  },
];

export default function HomePage() {
  const { language, toggleLanguage, t } = useLanguage();
  const [backendState, setBackendState] = useState<BackendState>("checking");
  const arabic = language === "ar";

  useEffect(() => {
    let active = true;
    getBackendHealth()
      .then(() => {
        if (active) setBackendState("healthy");
      })
      .catch(() => {
        if (active) setBackendState("unavailable");
      });
    return () => {
      active = false;
    };
  }, []);

  const healthLabel =
    backendState === "healthy"
      ? arabic
        ? "متصل"
        : "Connected"
      : backendState === "unavailable"
        ? arabic
          ? "غير متاح"
          : "Unavailable"
        : arabic
          ? "جارٍ الفحص"
          : "Checking";

  return (
    <div className="wood-shell fade-in h-screen overflow-y-auto px-5 py-6 md:px-8 md:py-8">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 pb-12">
        <header className="rounded-3xl border border-[#d9a441]/25 bg-black/35 p-6 shadow-[0_24px_80px_rgba(0,0,0,0.32)] backdrop-blur-xl md:p-8">
          <div className="flex flex-wrap items-start justify-between gap-5">
            <div className="max-w-3xl">
              <div className="mb-3 flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.22em] text-[#d9a441]">
                <span>{t("home.subtitle")}</span>
                <span className="rounded-full border border-[#d9a441]/25 bg-[#d9a441]/10 px-3 py-1 normal-case tracking-normal text-[#f0c56d]">
                  UAT · staging-demo-buyer
                </span>
              </div>
              <h1 className="text-3xl font-semibold tracking-tight text-white md:text-5xl">
                {t("home.title")}
              </h1>
              <p className="mt-4 max-w-2xl text-sm leading-7 text-white/60 md:text-base">
                {arabic
                  ? "مساحة عمل محاسبية مبنية على الأدلة: طابق، راجع، اعتمد، ثم سجل مع تحقق كامل وسجل تدقيق."
                  : "An evidence-first accounting workspace: reconcile, review, approve, register, and verify with a complete audit trail."}
              </p>
            </div>

            <button
              onClick={toggleLanguage}
              className="rounded-full border border-[#d9a441]/45 bg-[#d9a441]/10 px-4 py-2 text-sm font-semibold text-[#f0c56d] transition hover:bg-[#d9a441]/20"
              title={language === "en" ? "تحويل إلى العربية" : "Switch to English"}
            >
              {language === "en" ? "العربية" : "English"}
            </button>
          </div>
        </header>

        <section className="grid gap-4 md:grid-cols-3">
          <div className="rounded-3xl border border-white/10 bg-white/[0.045] p-5 backdrop-blur-xl md:col-span-2">
            <div className="text-xs uppercase tracking-[0.18em] text-white/40">
              {arabic ? "حالة المنصة" : "Platform status"}
            </div>
            <div className="mt-4 flex flex-wrap items-end justify-between gap-4">
              <div>
                <div className="text-2xl font-semibold text-white">
                  {arabic ? "BOB-2 Accounting Cockpit" : "BOB-2 Accounting Cockpit"}
                </div>
                <div className="mt-2 text-sm text-white/50">
                  {arabic ? "واجهة UAT مرتبطة بالـBackend وOdoo التجريبي" : "UAT frontend connected to the backend and isolated Odoo"}
                </div>
              </div>
              <div className="rounded-2xl border border-white/10 bg-black/25 px-4 py-3 text-right">
                <div className="text-xs text-white/40">Backend</div>
                <div
                  className={`mt-1 text-sm font-semibold ${
                    backendState === "healthy"
                      ? "text-emerald-300"
                      : backendState === "unavailable"
                        ? "text-rose-300"
                        : "text-amber-200"
                  }`}
                >
                  {healthLabel}
                </div>
              </div>
            </div>
          </div>

          <div className="rounded-3xl border border-[#d9a441]/20 bg-gradient-to-br from-[#d9a441]/15 to-black/20 p-5">
            <div className="text-xs uppercase tracking-[0.18em] text-[#d9a441]">
              {arabic ? "بوابة الأمان" : "Safety gate"}
            </div>
            <div className="mt-4 text-3xl font-semibold text-white">Human approval</div>
            <p className="mt-3 text-sm leading-6 text-white/55">
              {arabic
                ? "لا ترحيل مالي تلقائي. الكتابة تأتي بعد الاعتماد وتبقى قابلة للتحقق."
                : "No automatic financial posting. Writes follow approval and remain independently verifiable."}
            </p>
          </div>
        </section>

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {actions.map((action) => (
            <Link
              key={action.href}
              href={action.href}
              className="group rounded-3xl border border-white/10 bg-white/[0.04] p-5 transition duration-300 hover:-translate-y-1 hover:border-[#d9a441]/35 hover:bg-white/[0.065]"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="rounded-full border border-white/10 bg-black/20 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-white/45">
                  {action.badge}
                </span>
                <span className="text-[#d9a441] transition-transform group-hover:translate-x-1">↗</span>
              </div>
              <h2 className="mt-8 text-xl font-semibold text-white">
                {arabic ? action.titleAr : action.title}
              </h2>
              <p className="mt-3 text-sm leading-6 text-white/50">
                {arabic ? action.descriptionAr : action.description}
              </p>
            </Link>
          ))}
        </section>
      </div>
    </div>
  );
}
