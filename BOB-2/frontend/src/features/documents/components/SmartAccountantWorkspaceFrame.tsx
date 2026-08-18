"use client";

import type { ReactNode } from "react";

import { useLanguage } from "@/lib/LanguageContext";

type SmartAccountantWorkspaceFrameProps = Readonly<{
  children: ReactNode;
}>;

export function SmartAccountantWorkspaceFrame({
  children,
}: SmartAccountantWorkspaceFrameProps) {
  const { language } = useLanguage();
  const ar = language === "ar";

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden" dir={ar ? "rtl" : "ltr"}>
      <div className="min-h-0 flex-1 overflow-hidden [&>.wood-shell]:!h-full">
        {children}
      </div>
    </div>
  );
}
