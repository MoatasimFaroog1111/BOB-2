const DIACRITICS = /[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]/g;
const NON_ALNUM = /[^a-z0-9\u0600-\u06FF\s]/g;
const ARABIC_TO_LATIN: Record<string, string> = {
  ا: "a", أ: "a", إ: "i", آ: "a", ء: "a", ؤ: "o", ئ: "e", ب: "b",
  ت: "t", ث: "th", ج: "j", ح: "h", خ: "kh", د: "d", ذ: "th", ر: "r",
  ز: "z", س: "s", ش: "sh", ص: "s", ض: "d", ط: "t", ظ: "z", ع: "a",
  غ: "gh", ف: "f", ق: "q", ك: "k", ل: "l", م: "m", ن: "n", ه: "h",
  ة: "a", و: "w", ي: "y", ى: "a",
};

export const normalizeLookupValue = (value: string): string =>
  value.trim().replace(/\s+/g, " ").toLowerCase();

export const normalizePartnerName = (value: string): string => (value || "")
  .normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
  .replace(DIACRITICS, "").replace(/ـ/g, "").replace(/[أإآ]/g, "ا")
  .replace(/ى/g, "ي").replace(/ة/g, "ه").replace(NON_ALNUM, " ")
  .replace(/\b(company|co|corp|corporation|inc|ltd|llc|est)\b/g, " ")
  .replace(/(?:شركة|مؤسسه|مؤسسة|مكتب|مقاولات|التجارية|العامه|العامة)/g, " ")
  .replace(/\s+/g, " ").trim();

const transliterate = (value: string): string => Array.from(value)
  .map((character) => ARABIC_TO_LATIN[character] ?? character).join("")
  .replace(/\s+/g, " ").trim();

const bigrams = (value: string): string[] => {
  const cleaned = value.replace(/\s+/g, " ").trim();
  if (cleaned.length < 2) return cleaned ? [cleaned] : [];
  return Array.from({ length: cleaned.length - 1 }, (_, index) => cleaned.slice(index, index + 2));
};

const dice = (left: string, right: string): number => {
  if (!left || !right) return 0;
  if (left === right) return 1;
  const a = bigrams(left); const b = bigrams(right);
  if (!a.length || !b.length) return 0;
  const counts = new Map<string, number>();
  a.forEach((gram) => counts.set(gram, (counts.get(gram) ?? 0) + 1));
  let overlap = 0;
  b.forEach((gram) => {
    const count = counts.get(gram) ?? 0;
    if (count > 0) { overlap += 1; counts.set(gram, count - 1); }
  });
  return (2 * overlap) / (a.length + b.length);
};

const tokenOverlap = (left: string, right: string): number => {
  const a = new Set(left.split(" ").filter(Boolean));
  const b = new Set(right.split(" ").filter(Boolean));
  if (!a.size || !b.size) return 0;
  return Array.from(a).filter((token) => b.has(token)).length / Math.max(a.size, b.size);
};

export const partnerSimilarityScore = (queryRaw: string, candidateRaw: string): number => {
  const query = normalizePartnerName(queryRaw); const candidate = normalizePartnerName(candidateRaw);
  if (!query || !candidate) return 0;
  if (query === candidate) return 1;
  const boost = candidate.includes(query) || query.includes(candidate) ? 0.15 : 0;
  const nativeScore = dice(query, candidate) * 0.7 + tokenOverlap(query, candidate) * 0.3;
  const latinQuery = transliterate(query); const latinCandidate = transliterate(candidate);
  const crossLingual = dice(latinQuery, latinCandidate) * 0.65
    + tokenOverlap(latinQuery, latinCandidate) * 0.35;
  return Math.min(1, Math.max(nativeScore, crossLingual) + boost);
};
