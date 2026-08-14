"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { documentsGateway } from "@/features/documents/api/documentsGateway";
import { DailyBankReviewStatusStrip } from "@/features/documents/components/DailyBankReviewStatusStrip";
import type { DailyBankReviewDraft } from "@/features/documents/lib/dailyBankReview";
import {
  DAILY_BANK_REVIEW_EVENT,
  loadDailyBankReviewDraft,
  saveDailyBankReviewDraft,
} from "@/features/documents/lib/dailyBankReviewSession";
import { useLanguage } from "@/lib/LanguageContext";

export function DailyBankReviewActionBar() {
  const { language } = useLanguage();
  const router = useRouter();
  const [draft, setDraft] = useState<DailyBankReviewDraft | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const refresh = () => setDraft(loadDailyBankReviewDraft());
    refresh();
    window.addEventListener(DAILY_BANK_REVIEW_EVENT, refresh);
    return () => window.removeEventListener(DAILY_BANK_REVIEW_EVENT, refresh);
  }, []);

  if (!draft) return null;

  const submitForReview = async () => {
    if (submitting || draft.submitted) {
      if (draft.submitted) router.push("/audit");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const response = await documentsGateway.submitDailyBankReview({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: draft.documentId,
          journal_id: draft.journalId,
          company_id: draft.companyId || null,
        }),
      });
      if (!response.ok) throw new Error(await response.text());
      const result = await response.json();
      const reviewIds = Array.isArray(result.reviews)
        ? result.reviews.map((item: any) => Number(item.approval_id)).filter(Number.isFinite)
        : [];
      const submittedDraft = { ...draft, submitted: true, reviewIds };
      saveDailyBankReviewDraft(submittedDraft);
      setDraft(submittedDraft);
      router.push("/audit");
    } catch (err: any) {
      console.error(err);
      setError(String(err?.message || err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <DailyBankReviewStatusStrip
      language={language}
      entryCount={draft.entries.length}
      transactionCount={draft.transactionCount}
      unresolvedCount={draft.unresolvedCount}
      lowConfidenceCount={draft.lowConfidenceCount}
      submitted={Boolean(draft.submitted)}
      submitting={submitting}
      error={error}
      onAction={() => void submitForReview()}
    />
  );
}
