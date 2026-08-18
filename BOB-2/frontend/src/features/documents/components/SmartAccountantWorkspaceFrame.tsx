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
      {statusBar ? <div className="shrink-0">{statusBar}</div> : null}

      <div className="min-h-0 flex-1 overflow-hidden [&>.wood-shell]:!h-full">
        {children}
      </div>
    </div>
  );
}
