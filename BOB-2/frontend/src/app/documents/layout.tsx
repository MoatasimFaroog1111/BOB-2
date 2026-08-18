import type { ReactNode } from "react";

import { DailyBankReviewActionBar } from "@/features/documents/components/DailyBankReviewActionBar";
import { SmartAccountantWorkspaceFrame } from "@/features/documents/components/SmartAccountantWorkspaceFrame";

export default function DocumentsLayout({ children }: { children: ReactNode }) {
  return (
    <SmartAccountantWorkspaceFrame statusBar={<DailyBankReviewActionBar />}>
      {children}
    </SmartAccountantWorkspaceFrame>
  );
}
