import type { ReactNode } from "react";

import { DailyBankEvidenceManager } from "@/features/audit/components/DailyBankEvidenceManager";
import { DailyBankReviewQueue } from "@/features/audit/components/DailyBankReviewQueue";

export default function AuditLayout({ children }: { children: ReactNode }) {
  return (
    <>
      {children}
      <DailyBankEvidenceManager />
      <DailyBankReviewQueue />
    </>
  );
}
