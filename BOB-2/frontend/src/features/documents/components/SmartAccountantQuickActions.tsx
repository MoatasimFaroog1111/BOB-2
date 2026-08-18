"use client";

import { useEffect } from "react";

import {
  SMART_ACCOUNTANT_UI_ACTION_EVENT,
  type SmartAccountantUiAction,
} from "@/features/documents/model/smartAccountantUiEvents";

export function SmartAccountantQuickActions({
  disabled,
  onChoosePrompt,
  onAnalyzeDocument,
  onManualEntry,
}: Readonly<{
  language: string;
  disabled: boolean;
  onChoosePrompt: (prompt: string) => void;
  onAnalyzeDocument: () => void;
  onManualEntry: () => void;
}>) {
  useEffect(() => {
    const handleSidebarAction = (event: Event) => {
      if (disabled) return;
      const detail = (event as CustomEvent<SmartAccountantUiAction>).detail;
      if (!detail) return;

      if (detail.type === "prompt") {
        onChoosePrompt(detail.prompt);
        return;
      }

      if (detail.type === "analyze-document") {
        onAnalyzeDocument();
      }
    };

    window.addEventListener(SMART_ACCOUNTANT_UI_ACTION_EVENT, handleSidebarAction);
    return () => window.removeEventListener(SMART_ACCOUNTANT_UI_ACTION_EVENT, handleSidebarAction);
  }, [disabled, onAnalyzeDocument, onChoosePrompt]);

  // Manual entry remains available through the sidebar via the existing direct callback.
  // Keeping it in the prop contract avoids changing the SmartAccountantPanel boundary.
  void onManualEntry;

  return null;
}
