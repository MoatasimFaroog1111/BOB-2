"use client";

import type { ReactNode } from "react";

import { useLanguage } from "@/lib/LanguageContext";

type SmartAccountantWorkspaceFrameProps = Readonly<{
  children: ReactNode;
  statusBar?: ReactNode;
}>;

export function SmartAccountantWorkspaceFrame({
  children,
  statusBar,
}: SmartAccountantWorkspaceFrameProps) {
  const { language } = useLanguage();
  const ar = language === "ar";

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden" dir={ar ? "rtl" : "ltr"}>
      <header className="shrink-0 border-b border-white/10 bg-black/20 px-4 py-2 backdrop-blur-xl md:px-5">
        <div className="flex min-h-10 flex-wrap items-center gap-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-amber-400/20 bg-amber-400/10 text-sm text-amber-200">
              ✦
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h1 className="truncate text-sm font-black tracking-wide text-white">
                  {ar ? "المحاسب الذكي" : "Smart Accountant"}
                </h1>
                <span className="hidden rounded-full border border-emerald-400/15 bg-emerald-400/[0.07] px-2 py-0.5 text-[8px] font-bold text-emerald-300 sm:inline">
                  AI WORKSPACE
                </span>
              </div>
              <p className="mt-0.5 hidden truncate text-[9px] text-white/35 md:block">
                {ar
                  ? "مكتب محاسبي موحّد — التحليل أولاً والجدول عند الحاجة"
                  : "Unified accounting desk — analysis first, spreadsheet when needed"}
              </p>
            </div>
          </div>

          <div className="ms-auto flex min-w-max items-center gap-1.5 text-[8.5px] font-semibold">
            <span className="rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-white/45">
              {ar ? "مراجعة بشرية قبل الترحيل" : "Human review before posting"}
            </span>
            <span className="hidden rounded-full border border-emerald-400/15 bg-emerald-400/[0.06] px-2.5 py-1 text-emerald-300/80 sm:inline">
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
