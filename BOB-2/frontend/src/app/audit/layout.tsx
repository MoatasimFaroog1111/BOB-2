import type { ReactNode } from "react";

import { DailyBankReviewQueue } from "@/features/audit/components/DailyBankReviewQueue";

export default function AuditLayout({ children }: { children: ReactNode }) {
  return (
    <>
      {children}
      <DailyBankReviewQueue />
    </>
  );
}
