import type { DailyBankReviewDraft } from "@/features/documents/lib/dailyBankReview";

const STORAGE_KEY = "guardian.dailyBankReviewDraft.v1";
export const DAILY_BANK_REVIEW_EVENT = "guardian:daily-bank-review-draft";

export function saveDailyBankReviewDraft(draft: DailyBankReviewDraft | null): void {
  if (typeof window === "undefined") return;
  if (draft) {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(draft));
  } else {
    window.sessionStorage.removeItem(STORAGE_KEY);
  }
  window.dispatchEvent(new CustomEvent(DAILY_BANK_REVIEW_EVENT));
}

export function loadDailyBankReviewDraft(): DailyBankReviewDraft | null {
  if (typeof window === "undefined") return null;
  const raw = window.sessionStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as DailyBankReviewDraft;
    if (!value || !Number.isFinite(Number(value.documentId)) || !Array.isArray(value.entries)) {
      return null;
    }
    return value;
  } catch {
    return null;
  }
}
