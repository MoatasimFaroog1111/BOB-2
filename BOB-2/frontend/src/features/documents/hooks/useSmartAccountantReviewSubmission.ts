"use client";

import { useCallback, useEffect, useState } from "react";

import { documentsGateway } from "@/features/documents/api/documentsGateway";
import type { DailyBankReviewDraft } from "@/features/documents/lib/dailyBankReview";
import {
  DAILY_BANK_REVIEW_EVENT,
  loadDailyBankReviewDraft,
  saveDailyBankReviewDraft,
} from "@/features/documents/lib/dailyBankReviewSession";

type ReviewSubmissionState = "idle" | "submitting" | "submitted" | "error";

export function useSmartAccountantReviewSubmission() {
  const [draft, setDraft] = useState<DailyBankReviewDraft | null>(() => loadDailyBankReviewDraft());
  const [state, setState] = useState<ReviewSubmissionState>(draft?.submitted ? "submitted" : "idle");
  const [error, setError] = useState("");

  useEffect(() => {
    const syncDraft = () => {
      const next = loadDailyBankReviewDraft();
      setDraft(next);
      setState(next?.submitted ? "submitted" : "idle");
      setError("");
    };

    window.addEventListener(DAILY_BANK_REVIEW_EVENT, syncDraft);
    return () => window.removeEventListener(DAILY_BANK_REVIEW_EVENT, syncDraft);
  }, []);

  const submit = useCallback(async () => {
    if (!draft || draft.submitted || state === "submitting") return null;

    setState("submitting");
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
        ? result.reviews.map((item: { approval_id?: unknown }) => Number(item.approval_id)).filter(Number.isFinite)
        : [];
      const submittedDraft: DailyBankReviewDraft = {
        ...draft,
        submitted: true,
        reviewIds,
      };
      setDraft(submittedDraft);
      saveDailyBankReviewDraft(submittedDraft);
      setState("submitted");
      return result;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setState("error");
      throw err;
    }
  }, [draft, state]);

  return {
    draft,
    state,
    error,
    canSubmit: Boolean(draft && !draft.submitted),
    submit,
  };
}
