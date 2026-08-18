"use client";

import type { ReactNode } from "react";
import Link from "next/link";

import { useLanguage } from "@/lib/LanguageContext";

type SmartAccountantWorkspaceFrameProps = Readonly<{
  children: ReactNode;
  statusBar?: ReactNode;
}>;

const workspaceLinks = [
  { href: "/documents", ar: "مساحة العمل", en: "Workspace" },
  { href: "/bank-reconciliation", ar: "البنك", en: "Bank" },
  { href: "/audit", ar: "التدقيق", en: "Audit" },
  { href: "/erp", ar: "ERP", en: "ERP" },
  { href: "/settings", ar: "التكاملات", en: "Integrations" },
] as const;

export function SmartAccountantWorkspaceFrame({
  children,
  statusBar,
}: SmartAccountantWorkspaceFrameProps) {
  const { language } = useLanguage();
  const isArabic = language === "ar";

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden" dir={isArabic ? "rtl" : "ltr"}>
      <header className="shrink-0 border-b border-white/10 bg-black/20 px-4 py-2.5 backdrop-blur-xl md:px-6">
        <div className="flex items-center gap-3 overflow-x-auto">
          <div className="flex min-w-max items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-amber-400/25 bg-amber-400/10 text-lg shadow-[0_0_24px_rgba(217,164,65,0.08)]">
              ✦
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-sm font-bold tracking-wide text-white md:text-base">
                  {isArabic ? "المحاسب الذكي" : "Smart Accountant"}
                </h1>
                <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2 py-0.5 text-[9px] font-bold text-emerald-300">
                  AI WORKSPACE
                </span>
              </div>
              <p className="mt-0.5 text-[10px] text-white/45">
                {isArabic
                  ? "مركز عمل محاسبي موحّد للتحليل، المستندات، القيود، البنك والتدقيق"
                  : "One accounting workspace for analysis, documents, journals, banking and audit"}
              </p>
            </div>
          </div>

          <div className="h-8 w-px shrink-0 bg-white/10" />

          <nav
            className="flex min-w-max items-center gap-1.5"
            aria-label={isArabic ? "أوضاع المحاسب الذكي" : "Smart accountant modes"}
          >
            {workspaceLinks.map((item) => {
              const active = item.href === "/documents";
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`rounded-lg border px-3 py-1.5 text-[10.5px] font-semibold transition-all ${
                    active
                      ? "border-amber-400/30 bg-amber-400/10 text-amber-300"
                      : "border-white/10 bg-white/[0.03] text-white/60 hover:border-white/20 hover:bg-white/[0.06] hover:text-white"
                  }`}
                >
                  {isArabic ? item.ar : item.en}
                </Link>
              );
            })}
          </nav>

          <div className="flex-1" />

          <div className="flex min-w-max items-center gap-2 text-[9.5px] font-medium text-white/50">
            <span className="rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1">
              {isArabic ? "مراجعة بشرية قبل الترحيل" : "Human review before posting"}
            </span>
            <span className="rounded-full border border-emerald-400/15 bg-emerald-400/[0.06] px-2.5 py-1 text-emerald-300/80">
              Audit-safe
            </span>
          </div>
        </div>
      </header>

      {statusBar ? <div className="shrink-0">{statusBar}</div> : null}

      <div className="min-h-0 flex-1 overflow-hidden [&>.wood-shell]:!h-full">
        {children}
      </div>
    </div>
  );
}
