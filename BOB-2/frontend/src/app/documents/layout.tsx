import type { ReactNode } from "react";

import { DailyBankReviewActionBar } from "@/features/documents/components/DailyBankReviewActionBar";

export default function DocumentsLayout({ children }: { children: ReactNode }) {
  return (
    <>
      {children}
      <DailyBankReviewActionBar />
    </>
  );
}
