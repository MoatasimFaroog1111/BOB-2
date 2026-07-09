"use client";

import { useEffect, useMemo, useState } from "react";
import { API_BASE_URL } from "@/lib/api";

interface Transaction {
  date: string;
  description: string;
  main_description?: string;
  details?: string[];
  amount: number;
  debit?: number | null;
  credit?: number | null;
  row_number: number;
  suggested_action?: string;
  suggested_action_label?: string;
  confidence?: number;
  explanation?: string;
  detected_category?: string;
  ai_suggested_account?: string;
}

interface Props {
  rows: Transaction[];
  isAr: boolean;
  bankAccountLabel?: string;
  companyId?: number | string | null;
  bankJournalId?: number | string | null;
  bankAccountId?: number | string | null;
}

interface LookupOption {
  id?: number | string;
  code?: string;
  name: string;
  label: string;
}

interface OdooSuggestion {
  row_number?: number | null;
  date?: string;
  amount?: number;
  suggested_account_id?: number | null;
  suggested_account_label?: string;
  suggested_partner_id?: number | null;
  suggested_partner_label?: string;
  suggested_analytic_account_id?: number | null;
  suggested_analytic_account_label?: string;
  confidence?: number;
  reason?: string;
  source?: string;
  needs_review?: boolean;
}

interface SuggestedRow extends Transaction {
  suggested_account_id?: number | null;
  suggested_account_label: string;
  suggested_partner_id?: number | null;
  suggested_partner_label: string;
  suggested_analytic_account_id?: number | null;
  suggested_analytic_account_label: string;
  suggestion_confidence: number;
  suggestion_reason: string;
  suggestion_source: string;
  suggestion_needs_review: boolean;
}

interface PostingLinePreview {
  account_id: number;
  account_label: string;
  debit: number;
  credit: number;
  name: string;
  partner_id?: number;
  partner_label?: string;
  analytic_account_id?: number;
  analytic_account_label?: string;
}

interface AttachmentInfo {
  file: File;
  name: string;
  type: string;
  size: number;
}

interface PostingPreview {
  key: string;
  row: SuggestedRow;
  payload: any;
  lines: PostingLinePreview[];
  attachment?: AttachmentInfo;
  warning?: string;
}

type BulkResult = {
  status: "pending" | "success" | "error";
  message: string;
};

function selectedCompanyFromStorage() {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem("selectedCompanyId");
  const parsed = raw ? Number(raw) : NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function keyFor(row: { row_number?: number | null; date?: string | null; amount?: number | null }) {
  return `${row.row_number ?? ""}|${row.date || ""}|${Number(row.amount || 0).toFixed(2)}`;
}

function round2(value: number) {
  return Math.round((Number(value || 0) + Number.EPSILON) * 100) / 100;
}

function fmt(value?: number | null) {
  return Number(value || 0).toLocaleString("en-SA", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtFileSize(bytes?: number) {
  const value = Number(bytes || 0);
  if (!value) return "";
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / 1024 / 1024).toFixed(2)} MB`;
}

function pct(value?: number) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function clean(value: any) {
  return String(value || "")
    .toLowerCase()
    .replace(/[أإآ]/g, "ا")
    .replace(/ى/g, "ي")
    .replace(/ة/g, "ه")
    .replace(/[\u064B-\u065F\u0670]/g, "")
    .replace(/[^\w\u0600-\u06FF]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function rowText(row: Transaction) {
  return [row.main_description, row.description, ...(row.details || []), row.detected_category, row.suggested_action, row.suggested_action_label].filter(Boolean).join(" ");
}

function asOptions(data: any): LookupOption[] {
  const arr = Array.isArray(data) ? data : data?.accounts || data?.partners || data?.analytic_accounts || data?.analyticAccounts || data?.items || [];
  return arr
    .map((item: any) => ({
      id: item.id,
      code: item.code || "",
      name: item.name || item.display_name || "",
      label: `${item.code || ""} ${item.name || item.display_name || ""}${item.vat ? ` - ${item.vat}` : ""}`.trim(),
    }))
    .filter((item: LookupOption) => item.label);
}

function hasAny(text: string, patterns: string[]) {
  return patterns.some(pattern => text.includes(clean(pattern)) || new RegExp(pattern, "i").test(text));
}

function optionScore(option: LookupOption, terms: string[]) {
  const label = clean(`${option.code || ""} ${option.name || ""} ${option.label || ""}`);
  let score = 0;
  terms.forEach(term => {
    const t = clean(term);
    if (!t) return;
    if (label.includes(t)) score += 10;
    t.split(" ").filter(part => part.length > 2).forEach(part => {
      if (label.includes(part)) score += 2;
    });
  });
  return score;
}

function bestOption(options: LookupOption[], terms: string[], minimumScore = 8) {
  let best: LookupOption | undefined;
  let bestScore = 0;
  options.forEach(option => {
    const score = optionScore(option, terms);
    if (score > bestScore) {
      best = option;
      bestScore = score;
    }
  });
  return bestScore >= minimumScore ? best : undefined;
}

function termsForAccount(row: Transaction) {
  const text = clean(rowText(row));
  if (hasAny(text, ["عمولة", "رسوم", "fee", "charge", "commission"])) return ["مصروفات بنكية", "رسوم بنكية", "bank fees", "bank charges", "عمولات بنكية", "finance charges"];
  if (hasAny(text, ["vat", "ضريبة", "الضريبة المضافة"])) return ["ضريبة القيمة المضافة", "vat", "input vat", "value added tax"];
  if (hasAny(text, ["payroll", "salary", "wps", "رواتب", "راتب", "ملف"])) return ["رواتب", "اجور", "wages", "salaries", "payroll"];
  if (hasAny(text, ["stc", "اتصالات", "communication", "telecom"])) return ["اتصالات", "هاتف", "internet", "communication", "telephone", "telecom"];
  if (hasAny(text, ["residents", "مقيم", "خدمات المقيمين", "biller id", "sadad", "سداد"])) return ["رسوم حكومية", "government", "sadad", "مقيم", "اقامات", "iqama", "residents"];
  if (hasAny(text, ["rent", "lease", "ايجار"])) return ["ايجار", "rent", "lease"];
  if (hasAny(text, ["fuel", "aldrees", "وقود", "محروقات"])) return ["وقود", "fuel", "gasoline", "محروقات"];
  if (Number(row.amount || 0) > 0) return ["ايرادات", "revenue", "receivable", "customer", "income", "other income", "clearing"];
  return ["موردون", "payable", "expenses", "purchase", "مصروف", "تسوية", "suspense", "clearing"];
}

function fallbackAccount(accounts: LookupOption[], row: Transaction) {
  const categoryMatch = bestOption(accounts, termsForAccount(row));
  if (categoryMatch) return categoryMatch.label;
  const suspense = bestOption(accounts, ["تسوية", "suspense", "clearing", "وسيط", "temporary"], 6);
  return suspense?.label || accounts[0]?.label || "";
}

function fallbackPartner(partners: LookupOption[], row: Transaction) {
  const text = clean(rowText(row));
  let best: LookupOption | undefined;
  let bestScore = 0;
  partners.forEach(partner => {
    const partnerName = clean(partner.name || partner.label);
    if (!partnerName || partnerName.length < 3) return;
    let score = 0;
    if (text.includes(partnerName)) score += 40;
    partnerName.split(" ").filter(token => token.length > 2).forEach(token => {
      if (text.includes(token)) score += 4;
    });
    if (score > bestScore) {
      best = partner;
      bestScore = score;
    }
  });
  return bestScore >= 8 ? best?.label || "" : "";
}

function fallbackAnalytic(analytics: LookupOption[], row: Transaction) {
  const text = clean(rowText(row));
  let best: LookupOption | undefined;
  let bestScore = 0;
  analytics.forEach(analytic => {
    const label = clean(analytic.label || analytic.name);
    let score = 0;
    label.split(" ").filter(token => token.length > 2).forEach(token => {
      if (text.includes(token)) score += 3;
    });
    if (score > bestScore) {
      best = analytic;
      bestScore = score;
    }
  });
  return bestScore >= 6 ? best?.label || "" : "";
}

function applySuggestion(row: Transaction, suggestion: OdooSuggestion | null, accounts: LookupOption[], partners: LookupOption[], analytics: LookupOption[]): SuggestedRow {
  const account = suggestion?.suggested_account_label || row.ai_suggested_account || fallbackAccount(accounts, row);
  const partner = suggestion?.suggested_partner_label || fallbackPartner(partners, row);
  const analytic = suggestion?.suggested_analytic_account_label || fallbackAnalytic(analytics, row);
  const usedFallback = !suggestion?.suggested_account_label && Boolean(account);
  return {
    ...row,
    suggested_account_id: suggestion?.suggested_account_id || null,
    suggested_account_label: account,
    suggested_partner_id: suggestion?.suggested_partner_id || null,
    suggested_partner_label: partner,
    suggested_analytic_account_id: suggestion?.suggested_analytic_account_id || null,
    suggested_analytic_account_label: analytic,
    suggestion_confidence: Number(suggestion?.confidence || row.confidence || (usedFallback ? 0.58 : 0)),
    suggestion_reason: suggestion?.reason || row.explanation || (usedFallback ? "Local fallback from loaded Odoo accounts and transaction keywords after historical lookup was unavailable." : ""),
    suggestion_source: suggestion?.source || (usedFallback ? "local_odoo_lookup_fallback" : "odoo_historical_or_ai_review"),
    suggestion_needs_review: suggestion?.needs_review ?? true,
  };
}

function findOptionByValue(options: LookupOption[], value?: string, id?: number | string | null): LookupOption | undefined {
  if (id) {
    const byId = options.find(option => String(option.id) === String(id));
    if (byId) return byId;
  }
  const cleanedValue = clean(value || "");
  if (!cleanedValue) return undefined;
  const exact = options.find(option => clean(option.label) === cleanedValue || clean(`${option.code || ""} ${option.name || ""}`) === cleanedValue);
  if (exact) return exact;
  const firstToken = cleanedValue.split(" ")[0];
  if (/^\d{3,}$/.test(firstToken)) {
    const byCode = options.find(option => clean(option.code || "") === firstToken || clean(option.label).startsWith(firstToken));
    if (byCode) return byCode;
  }
  return options.find(option => clean(option.label).includes(cleanedValue) || cleanedValue.includes(clean(option.name)));
}

function isVatAccount(option?: LookupOption | null) {
  const label = clean(`${option?.code || ""} ${option?.name || ""} ${option?.label || ""}`);
  return Boolean(option) && (label.includes("vat input") || label.includes("input vat") || label.includes("value added tax") || label.includes("ضريبه القيمه المضافه") || label.includes("104041"));
}

function findVatInputAccount(accounts: LookupOption[]) {
  return accounts.find(option => isVatAccount(option)) || bestOption(accounts, ["104041", "VAT Input", "Input VAT", "ضريبة القيمة المضافة", "value added tax"], 6);
}

function findBankChargeAccount(accounts: LookupOption[]) {
  return bestOption(accounts, ["400051", "Other Bank Charges", "Bank Charges", "رسوم بنكية", "مصروفات بنكية", "عمولات بنكية"], 6);
}

function parseFirstMoney(patterns: RegExp[], text: string) {
  const normalized = String(text || "").replace(/,/g, " ");
  for (const pattern of patterns) {
    const match = normalized.match(pattern);
    if (match?.[1]) {
      const value = Number(String(match[1]).replace(/[^0-9.]/g, ""));
      if (Number.isFinite(value) && value > 0) return round2(value);
    }
  }
  return 0;
}

function extractVatAmount(row: Transaction, totalAmount: number) {
  const text = rowText(row);
  const explicitVat = parseFirstMoney([
    /VAT\s*AMOUNT\s*0*([0-9]+(?:\.[0-9]+)?)/i,
    /VAT\s*0*([0-9]+(?:\.[0-9]+)?)/i,
    /الضريبه\s*المضافه\s*0*([0-9]+(?:\.[0-9]+)?)/i,
    /الضريبة\s*المضافة\s*0*([0-9]+(?:\.[0-9]+)?)/i,
  ], text);
  if (explicitVat > 0 && explicitVat < totalAmount) return explicitVat;

  const hasVatSignal = /VAT\s*%?\s*15|VAT%\s*15|15\s*%|ضريبةالقيمةالمضافة|ضريبه\s*القيمه\s*المضافه|الضريبة\s*المضافة/i.test(text);
  if (hasVatSignal && totalAmount > 0) return round2(totalAmount * 15 / 115);
  return 0;
}

function firstLine(value: string, max = 120) {
  const plain = String(value || "").replace(/\s+/g, " ").trim();
  return plain.length > max ? `${plain.slice(0, max - 1)}…` : plain;
}

async function jsonOrNull(response: Response) {
  return response.json().catch(() => null);
}

async function delay(ms: number) {
  await new Promise(resolve => setTimeout(resolve, ms));
}

async function fileToBase64(file: File): Promise<string> {
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("Failed to read attachment"));
    reader.readAsDataURL(file);
  });
}

export default function HistoricalJournalEntrySuggestionsEditor({ rows, isAr, companyId, bankJournalId, bankAccountId, bankAccountLabel }: Props) {
  const [suggestedRows, setSuggestedRows] = useState<SuggestedRow[]>(rows.map(row => applySuggestion(row, null, [], [], [])));
  const [accounts, setAccounts] = useState<LookupOption[]>([]);
  const [partners, setPartners] = useState<LookupOption[]>([]);
  const [analytics, setAnalytics] = useState<LookupOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [wideMode, setWideMode] = useState(false);
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({});
  const [preview, setPreview] = useState<PostingPreview | null>(null);
  const [posting, setPosting] = useState<Record<string, boolean>>({});
  const [posted, setPosted] = useState<Record<string, { move_name?: string; odoo_url?: string; attachment_name?: string }>>({});
  const [postError, setPostError] = useState<Record<string, string>>({});
  const [attachments, setAttachments] = useState<Record<string, AttachmentInfo>>({});
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkPosting, setBulkPosting] = useState(false);
  const [bulkResults, setBulkResults] = useState<Record<string, BulkResult>>({});

  const effectiveCompanyId = companyId || selectedCompanyFromStorage();

  const payload = useMemo(() => ({
    transactions: rows,
    company_id: effectiveCompanyId || null,
    bank_journal_id: bankJournalId ? Number(bankJournalId) : null,
    bank_account_id: bankAccountId ? Number(bankAccountId) : null,
    history_limit: 600,
  }), [rows, effectiveCompanyId, bankJournalId, bankAccountId]);

  useEffect(() => {
    let alive = true;

    async function loadInlineSuggestions() {
      if (!rows.length) {
        setSuggestedRows([]);
        return;
      }

      setLoading(true);
      setError("");
      setNotice("");

      try {
        const qs = effectiveCompanyId ? `?company_id=${effectiveCompanyId}` : "";

        const accountsResponse = await fetch(`${API_BASE_URL}/api/v1/erp/accounts${qs}`);
        const accountsData = await jsonOrNull(accountsResponse);
        const accountOptions = accountsResponse.ok ? asOptions(accountsData) : [];
        if (alive) setAccounts(accountOptions);
        await delay(250);

        const partnersResponse = await fetch(`${API_BASE_URL}/api/v1/erp/partners${qs}`);
        const partnersData = await jsonOrNull(partnersResponse);
        const partnerOptions = partnersResponse.ok ? asOptions(partnersData) : [];
        if (alive) setPartners(partnerOptions);
        await delay(250);

        const analyticsResponse = await fetch(`${API_BASE_URL}/api/v1/erp/analytic-accounts${qs}`);
        const analyticsData = await jsonOrNull(analyticsResponse);
        const analyticOptions = analyticsResponse.ok ? asOptions(analyticsData) : [];
        if (alive) setAnalytics(analyticOptions);
        await delay(300);

        let historyWarning = "";
        let historyItems: OdooSuggestion[] = [];
        try {
          const historyResponse = await fetch(`${API_BASE_URL}/api/v1/erp/bank-reconciliation/entry-suggestions`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          const historyData = await jsonOrNull(historyResponse);
          if (historyResponse.ok && Array.isArray(historyData?.items)) {
            historyItems = historyData.items;
          } else {
            const detail = historyData?.detail || `HTTP ${historyResponse.status}`;
            historyWarning = String(detail).includes("429")
              ? (isAr ? "تم تجاوز حد طلبات Odoo مؤقتًا، لذلك تم استخدام اقتراحات محلية من الحسابات والشركاء المحملين." : "Odoo rate limit was reached, so local suggestions from loaded accounts and partners were used.")
              : String(detail);
          }
        } catch (historyErr: any) {
          historyWarning = historyErr?.message || String(historyErr);
        }

        const suggestions = new Map<string, OdooSuggestion>();
        historyItems.forEach((item: OdooSuggestion) => {
          suggestions.set(keyFor({ row_number: item.row_number, date: item.date, amount: item.amount }), item);
        });

        const nextRows = rows.map(row => applySuggestion(row, suggestions.get(keyFor(row)) || null, accountOptions, partnerOptions, analyticOptions));

        if (!alive) return;
        setSuggestedRows(nextRows);
        const suggestedCount = nextRows.filter(row => row.suggested_account_label || row.suggested_partner_label).length;
        const historicalCount = nextRows.filter(row => row.suggestion_source === "odoo_historical_move_lines").length;
        setNotice(isAr
          ? `تم تجهيز الحسابات والشركاء أمام ${suggestedCount} عملية. المطابقة التاريخية: ${historicalCount}.`
          : `Prepared account and partner suggestions for ${suggestedCount} rows. Historical matches: ${historicalCount}.`);
        if (historyWarning) setError(historyWarning);
      } catch (err: any) {
        if (!alive) return;
        const fallbackRows = rows.map(row => applySuggestion(row, null, accounts, partners, analytics));
        setSuggestedRows(fallbackRows);
        setError((isAr ? "تعذر تحميل بيانات أودو بالكامل، وتم استخدام المتاح فقط: " : "Could not fully load Odoo data; using available data only: ") + (err?.message || err));
      } finally {
        if (alive) setLoading(false);
      }
    }

    loadInlineSuggestions();
    return () => { alive = false; };
  }, [payload, rows, isAr, effectiveCompanyId]);

  const accountList = "inline-odoo-account-suggestions";
  const partnerList = "inline-odoo-partner-suggestions";
  const analyticList = "inline-odoo-analytic-suggestions";

  const updateSuggestedRow = (index: number, patch: Partial<SuggestedRow>) => {
    setSuggestedRows(prev => prev.map((row, i) => i === index ? { ...row, ...patch } : row));
  };

  const onAttachFile = (row: SuggestedRow, file?: File | null) => {
    const rowKey = keyFor(row);
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      setPostError(prev => ({ ...prev, [rowKey]: isAr ? "حجم المستند أكبر من 10 MB." : "Attachment is larger than 10 MB." }));
      return;
    }
    setAttachments(prev => ({ ...prev, [rowKey]: { file, name: file.name, type: file.type || "application/octet-stream", size: file.size } }));
    setPostError(prev => ({ ...prev, [rowKey]: "" }));
  };

  const removeAttachment = (row: SuggestedRow) => {
    const rowKey = keyFor(row);
    setAttachments(prev => {
      const next = { ...prev };
      delete next[rowKey];
      return next;
    });
  };

  const buildPreview = (row: SuggestedRow): PostingPreview => {
    const rowKey = keyFor(row);
    const amount = round2(Math.abs(Number(row.amount || 0)));
    const attachment = attachments[rowKey];
    const vatAmount = row.amount < 0 ? extractVatAmount(row, amount) : 0;
    const vatDetected = vatAmount > 0;
    const vatAccount = vatDetected ? findVatInputAccount(accounts) : undefined;
    const originallySuggestedAccount = findOptionByValue(accounts, row.suggested_account_label, row.suggested_account_id);
    const bankChargeAccount = findBankChargeAccount(accounts);
    const counterAccount = vatDetected && isVatAccount(originallySuggestedAccount)
      ? (bankChargeAccount && !isVatAccount(bankChargeAccount) ? bankChargeAccount : originallySuggestedAccount)
      : originallySuggestedAccount;
    const partner = findOptionByValue(partners, row.suggested_partner_label, row.suggested_partner_id);
    const analytic = findOptionByValue(analytics, row.suggested_analytic_account_label, row.suggested_analytic_account_id);
    const description = firstLine(row.main_description || row.description || `Bank statement row ${row.row_number}`, 180);
    const ref = `BANK-STMT-ROW-${row.row_number || "NA"}-${row.date || "NO-DATE"}`;
    const bankId = bankAccountId ? Number(bankAccountId) : 0;
    const warning = !counterAccount?.id
      ? (isAr ? "لا يمكن الترحيل قبل اختيار حساب صحيح من أودو." : "Select a valid Odoo account before posting.")
      : vatDetected && !vatAccount?.id
        ? (isAr ? "تم اكتشاف ضريبة قيمة مضافة في البيان، لكن لم يتم العثور على حساب VAT Input في أودو." : "VAT was detected, but no VAT Input account was found in Odoo.")
        : !bankId
          ? (isAr ? "لا يمكن الترحيل قبل توفر حساب البنك المختار." : "The selected bank account is required before posting.")
          : amount <= 0
            ? (isAr ? "المبلغ صفر أو غير صالح." : "The amount is zero or invalid.")
            : "";

    const counterAmount = vatDetected && vatAccount?.id ? round2(amount - vatAmount) : amount;
    const counterLine: PostingLinePreview = {
      account_id: Number(counterAccount?.id || 0),
      account_label: counterAccount?.label || row.suggested_account_label || "—",
      debit: row.amount < 0 ? counterAmount : 0,
      credit: row.amount > 0 ? counterAmount : 0,
      name: description,
      partner_id: partner?.id ? Number(partner.id) : undefined,
      partner_label: partner?.label || row.suggested_partner_label || undefined,
      analytic_account_id: analytic?.id ? Number(analytic.id) : undefined,
      analytic_account_label: analytic?.label || row.suggested_analytic_account_label || undefined,
    };
    const vatLine: PostingLinePreview | null = vatDetected && vatAccount?.id ? {
      account_id: Number(vatAccount.id),
      account_label: vatAccount.label,
      debit: row.amount < 0 ? vatAmount : 0,
      credit: row.amount > 0 ? vatAmount : 0,
      name: `VAT Input - ${description}`,
      partner_id: partner?.id ? Number(partner.id) : undefined,
      partner_label: partner?.label || row.suggested_partner_label || undefined,
      analytic_account_id: analytic?.id ? Number(analytic.id) : undefined,
      analytic_account_label: analytic?.label || row.suggested_analytic_account_label || undefined,
    } : null;
    const bankLine: PostingLinePreview = {
      account_id: bankId,
      account_label: bankAccountLabel || (isAr ? "الحساب البنكي المختار" : "Selected bank account"),
      debit: row.amount > 0 ? amount : 0,
      credit: row.amount < 0 ? amount : 0,
      name: description,
    };
    const lines = vatLine ? [counterLine, vatLine, bankLine] : [counterLine, bankLine];
    return {
      key: rowKey,
      row,
      warning,
      lines,
      attachment,
      payload: {
        company_id: effectiveCompanyId ? Number(effectiveCompanyId) : null,
        journal_type: "bank",
        journal_id: bankJournalId ? Number(bankJournalId) : null,
        date: row.date || "",
        ref,
        filename: "bank_statement_reconciliation",
        amount: Number(row.amount || 0),
        partner_name: partner?.label || row.suggested_partner_label || "",
        attachment_name: attachment?.name || "",
        attachment_mimetype: attachment?.type || "",
        lines: lines.map(line => ({
          account_id: line.account_id,
          account_name: line.account_label,
          debit: line.debit,
          credit: line.credit,
          name: line.name,
          partner_id: line.partner_id,
          partner_name: line.partner_label || "",
          analytic_account_id: line.analytic_account_id,
          analytic_account_name: line.analytic_account_label || "",
        })),
      },
    };
  };

  const openPreview = (row: SuggestedRow) => setPreview(buildPreview(row));

  const postRow = async (row: SuggestedRow, options?: { showPreview?: boolean; throwOnError?: boolean }) => {
    const currentPreview = buildPreview(row);
    const showPreview = options?.showPreview !== false;
    if (showPreview) setPreview(currentPreview);
    if (currentPreview.warning) {
      if (options?.throwOnError) throw new Error(currentPreview.warning);
      return;
    }
    setPosting(prev => ({ ...prev, [currentPreview.key]: true }));
    setPostError(prev => ({ ...prev, [currentPreview.key]: "" }));
    try {
      const attachmentContent = currentPreview.attachment?.file ? await fileToBase64(currentPreview.attachment.file) : "";
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/register-bank-reconciliation-entry-v2`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...currentPreview.payload, attachment_content_base64: attachmentContent }),
      });
      const data = await jsonOrNull(response);
      if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
      setPosted(prev => ({ ...prev, [currentPreview.key]: { move_name: data?.move_name, odoo_url: data?.odoo_url, attachment_name: data?.attachment_name } }));
      const attachmentMessage = data?.attachment_name
        ? (isAr ? ` وتم إرفاق المستند: ${data.attachment_name}` : ` and attached: ${data.attachment_name}`)
        : data?.attachment_error
          ? (isAr ? `، لكن فشل إرفاق المستند: ${data.attachment_error}` : `, but attachment failed: ${data.attachment_error}`)
          : "";
      if (showPreview) setPreview(prev => prev ? { ...prev, warning: isAr ? `تم إنشاء القيد في Odoo: ${data?.move_name || data?.move_id}${attachmentMessage}` : `Created in Odoo: ${data?.move_name || data?.move_id}${attachmentMessage}` } : prev);
      if (data?.attachment_error) setPostError(prev => ({ ...prev, [currentPreview.key]: data.attachment_error }));
      return data;
    } catch (err: any) {
      setPostError(prev => ({ ...prev, [currentPreview.key]: err?.message || String(err) }));
      if (options?.throwOnError) throw err;
    } finally {
      setPosting(prev => ({ ...prev, [currentPreview.key]: false }));
    }
  };

  const postAllRows = async () => {
    if (bulkPosting) return;
    const targets = suggestedRows.filter(row => !posted[keyFor(row)]);
    const initialResults: Record<string, BulkResult> = {};
    targets.forEach(row => {
      initialResults[keyFor(row)] = { status: "pending", message: isAr ? "بانتظار الترحيل" : "Pending" };
    });
    setBulkResults(initialResults);
    setBulkPosting(true);

    for (const row of targets) {
      const rowKey = keyFor(row);
      try {
        await postRow(row, { showPreview: false, throwOnError: true });
        setBulkResults(prev => ({ ...prev, [rowKey]: { status: "success", message: isAr ? "تم الترحيل إلى Odoo" : "Posted to Odoo" } }));
      } catch (err: any) {
        setBulkResults(prev => ({ ...prev, [rowKey]: { status: "error", message: err?.message || String(err) } }));
      }
    }

    setBulkPosting(false);
  };

  if (!rows.length) {
    return <p className="p-6 text-center text-gray-500">{isAr ? "لا توجد عمليات تحتاج اقتراحات." : "No rows need suggestions."}</p>;
  }

  const bulkPreviews = suggestedRows.map(row => buildPreview(row));
  const bulkReadyCount = bulkPreviews.filter(item => !item.warning && !posted[item.key]).length;
  const bulkPostedCount = bulkPreviews.filter(item => Boolean(posted[item.key])).length;

  const shellClass = wideMode
    ? "fixed inset-3 z-[9999] overflow-hidden rounded-2xl border border-cyan-500/30 bg-[#050505] p-4 shadow-2xl flex flex-col"
    : "space-y-3";

  return (
    <div className={shellClass} dir={isAr ? "rtl" : "ltr"}>
      <datalist id={accountList}>{accounts.map((account, index) => <option key={index} value={account.label} />)}</datalist>
      <datalist id={partnerList}>{partners.map((partner, index) => <option key={index} value={partner.label} />)}</datalist>
      <datalist id={analyticList}>{analytics.map((analytic, index) => <option key={index} value={analytic.label} />)}</datalist>

      <div className="rounded-xl border border-cyan-500/25 bg-cyan-500/10 px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-sm font-bold text-cyan-200">{isAr ? "اقتراحات AI للحسابات والشركاء" : "AI account and partner suggestions"}</p>
            <p className="mt-1 text-[11px] text-white/60">
              {isAr
                ? "كل عملية يظهر أمامها الحساب والشريك. عند وجود VAT AMOUNT في البيان يتم فصل ضريبة القيمة المضافة تلقائيًا في سطر VAT Input قبل الترحيل."
                : "Each transaction shows its account and partner. When VAT AMOUNT exists in the statement, VAT is automatically split into a VAT Input line before posting."}
            </p>
          </div>
          <button onClick={() => setWideMode(prev => !prev)} className="rounded-lg border border-cyan-500/40 bg-cyan-500/15 px-3 py-1.5 text-xs font-bold text-cyan-200 hover:bg-cyan-500/25">
            {wideMode ? "↩" : "⛶"} {wideMode ? (isAr ? "رجوع" : "Back") : (isAr ? "توسعة الشاشة" : "Expand")}
          </button>
        </div>
      </div>

      {(loading || notice || error) && (
        <div className="flex flex-wrap gap-2 text-[11px]">
          {loading && <span className="rounded-lg border border-cyan-500/40 bg-cyan-500/15 px-3 py-1.5 font-bold text-cyan-200">{isAr ? "جاري تجهيز الاقتراحات من أودو..." : "Preparing suggestions from Odoo..."}</span>}
          {notice && <button type="button" onClick={() => setBulkOpen(true)} className="rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-1.5 text-start font-bold text-emerald-200 underline-offset-4 hover:bg-emerald-500/25 hover:underline">{notice} <span className="text-emerald-100/70">{isAr ? "اضغط لعرض وترحيل كافة القيود" : "Click to preview and post all entries"}</span></button>}
          {error && <span className="rounded-lg border border-amber-500/40 bg-amber-500/15 px-3 py-1.5 font-bold text-amber-200">{error}</span>}
        </div>
      )}

      <div className={`${wideMode ? "flex-1 min-h-0" : ""} overflow-auto rounded-xl border border-white/10 bg-black/20`}>
        <table className="w-full min-w-[1540px] text-[11px]">
          <thead className="sticky top-0 z-10 bg-zinc-950 text-white/60">
            <tr className="border-b border-white/10">
              <th className="px-3 py-2 text-center">#</th>
              <th className="px-3 py-2 text-start">{isAr ? "التاريخ" : "Date"}</th>
              <th className="px-3 py-2 text-start min-w-[300px]">{isAr ? "البيان / الوصف" : "Statement description"}</th>
              <th className="px-3 py-2 text-end">{isAr ? "المبلغ" : "Amount"}</th>
              <th className="px-3 py-2 text-start min-w-[260px]">{isAr ? "الحساب المقترح" : "Suggested account"}</th>
              <th className="px-3 py-2 text-start min-w-[220px]">{isAr ? "الشريك المقترح" : "Suggested partner"}</th>
              <th className="px-3 py-2 text-start min-w-[220px]">{isAr ? "الحساب التحليلي" : "Analytic account"}</th>
              <th className="px-3 py-2 text-center">{isAr ? "الثقة" : "Confidence"}</th>
              <th className="px-3 py-2 text-start min-w-[230px]">{isAr ? "مصدر الاقتراح" : "Suggestion source"}</th>
              <th className="px-3 py-2 text-center min-w-[260px]">{isAr ? "الإجراءات" : "Actions"}</th>
            </tr>
          </thead>
          <tbody>
            {suggestedRows.map((row, index) => {
              const rowKey = keyFor(row);
              const attachment = attachments[rowKey];
              const sourceLabel = row.suggestion_source === "odoo_historical_move_lines"
                ? (isAr ? "مطابقة تاريخية من أودو" : "Odoo historical match")
                : row.suggestion_source === "local_odoo_lookup_fallback"
                  ? (isAr ? "اقتراح محلي من بيانات أودو" : "Local Odoo lookup fallback")
                  : (isAr ? "اقتراح AI يحتاج مراجعة" : "AI suggestion needs review");
              const postedInfo = posted[rowKey];
              return (
                <tr key={`${row.row_number}-${row.date}-${row.amount}-${index}`} className="border-b border-white/5 align-top hover:bg-white/5">
                  <td className="px-3 py-2 text-center font-mono text-white/40">
                    <button onClick={() => setExpandedRows(prev => ({ ...prev, [rowKey]: !prev[rowKey] }))} className="me-1 rounded border border-white/10 px-1 text-white/60 hover:text-white">{expandedRows[rowKey] ? "▾" : "▸"}</button>
                    {row.row_number || index + 1}
                  </td>
                  <td className="px-3 py-2 font-mono text-white/70">{row.date || "—"}</td>
                  <td className="px-3 py-2 text-white">
                    <div className="font-semibold leading-relaxed">{expandedRows[rowKey] ? (row.main_description || row.description || "—") : firstLine(row.main_description || row.description || "—", 170)}</div>
                    {expandedRows[rowKey] && row.details && row.details.length > 0 && <div className="mt-2 space-y-1 text-white/45">{row.details.map((detail, detailIndex) => <div key={detailIndex}>{detail}</div>)}</div>}
                  </td>
                  <td className="px-3 py-2 text-end font-mono font-bold text-amber-300">{fmt(row.amount)} SAR</td>
                  <td className="px-3 py-2"><input list={accountList} value={row.suggested_account_label} onChange={event => updateSuggestedRow(index, { suggested_account_label: event.target.value, suggested_account_id: null })} placeholder={isAr ? "اختر الحساب من أودو" : "Select Odoo account"} className="w-full rounded-lg border border-cyan-500/20 bg-black/40 px-2 py-2 text-white outline-none focus:border-cyan-400" /></td>
                  <td className="px-3 py-2"><input list={partnerList} value={row.suggested_partner_label} onChange={event => updateSuggestedRow(index, { suggested_partner_label: event.target.value, suggested_partner_id: null })} placeholder={isAr ? "اختر الشريك" : "Select partner"} className="w-full rounded-lg border border-purple-500/20 bg-black/40 px-2 py-2 text-white outline-none focus:border-purple-400" /></td>
                  <td className="px-3 py-2"><input list={analyticList} value={row.suggested_analytic_account_label} onChange={event => updateSuggestedRow(index, { suggested_analytic_account_label: event.target.value, suggested_analytic_account_id: null })} placeholder={isAr ? "اختياري" : "Optional"} className="w-full rounded-lg border border-amber-500/20 bg-black/40 px-2 py-2 text-white outline-none focus:border-amber-400" /></td>
                  <td className="px-3 py-2 text-center"><span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${row.suggestion_confidence >= 0.7 ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300" : "border-amber-500/40 bg-amber-500/15 text-amber-300"}`}>{pct(row.suggestion_confidence)}</span></td>
                  <td className="px-3 py-2 text-white/55"><div className="font-bold text-cyan-200">{sourceLabel}</div><div className="mt-1 leading-relaxed">{expandedRows[rowKey] ? (row.suggestion_reason || (isAr ? "راجع الحساب والشريك قبل الاعتماد." : "Review the account and partner before approval.")) : firstLine(row.suggestion_reason || "", 120)}</div></td>
                  <td className="px-3 py-2 text-center">
                    <div className="flex flex-wrap items-center justify-center gap-2">
                      <button title={isAr ? "عرض ثم ترحيل القيد" : "Preview then post entry"} onClick={() => openPreview(row)} className="rounded-lg border border-blue-500/40 bg-blue-500/15 px-2 py-1 text-blue-200 hover:bg-blue-500/25">👁️🚀 {isAr ? "عرض ثم ترحيل" : "Preview & post"}</button>
                      <label title={isAr ? "إرفاق مستند" : "Attach document"} className="cursor-pointer rounded-lg border border-amber-500/40 bg-amber-500/15 px-2 py-1 text-amber-200 hover:bg-amber-500/25">
                        📎 {isAr ? "إرفاق" : "Attach"}
                        <input type="file" className="hidden" accept=".pdf,.png,.jpg,.jpeg,.webp,.xls,.xlsx,.csv,.ofx,.txt" onChange={event => onAttachFile(row, event.target.files?.[0])} />
                      </label>
                    </div>
                    {attachment && <div className="mt-1 flex items-center justify-center gap-1 text-[10px] text-amber-200"><span title={attachment.name}>📄 {firstLine(attachment.name, 28)} {fmtFileSize(attachment.size)}</span><button onClick={() => removeAttachment(row)} className="text-rose-300 hover:text-rose-200">✕</button></div>}
                    {postedInfo && <a href={postedInfo.odoo_url} target="_blank" rel="noreferrer" className="mt-1 block text-[10px] text-emerald-300 underline">✅ {postedInfo.move_name || "Odoo"}{postedInfo.attachment_name ? ` + ${isAr ? "مستند" : "document"}` : ""}</a>}
                    {postError[rowKey] && <div className="mt-1 text-[10px] text-rose-300">{postError[rowKey]}</div>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {bulkOpen && (
        <div className="fixed inset-0 z-[10001] flex items-center justify-center bg-black/75 p-4" onClick={() => !bulkPosting && setBulkOpen(false)}>
          <div className="flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-emerald-500/25 bg-zinc-950 shadow-2xl" onClick={event => event.stopPropagation()}>
            <div className="border-b border-white/10 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="text-lg font-bold text-white">🧾 {isAr ? "عرض وترحيل كافة القيود المقترحة" : "Preview and post all suggested entries"}</h3>
                  <p className="mt-1 text-xs text-white/55">{isAr ? "هذه شاشة مستقلة لمراجعة كل القيود. زر ترحيل كافة القيود سيرحل كل صف غير مرحّل مع مرفقه إن وجد." : "Review all entries here. Post all entries will post every unposted row with its attachment when available."}</p>
                </div>
                <button disabled={bulkPosting} onClick={() => setBulkOpen(false)} className="rounded-lg border border-white/10 px-3 py-1 text-white/70 hover:text-white disabled:opacity-40">✕</button>
              </div>
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                <span className="rounded-lg border border-cyan-500/40 bg-cyan-500/15 px-3 py-1.5 font-bold text-cyan-200">{isAr ? `إجمالي القيود: ${bulkPreviews.length}` : `Total entries: ${bulkPreviews.length}`}</span>
                <span className="rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-1.5 font-bold text-emerald-200">{isAr ? `جاهزة للترحيل: ${bulkReadyCount}` : `Ready: ${bulkReadyCount}`}</span>
                <span className="rounded-lg border border-amber-500/40 bg-amber-500/15 px-3 py-1.5 font-bold text-amber-200">{isAr ? `مرحّلة سابقًا: ${bulkPostedCount}` : `Already posted: ${bulkPostedCount}`}</span>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-auto p-4">
              <table className="w-full min-w-[980px] text-xs">
                <thead className="sticky top-0 bg-zinc-950 text-white/50">
                  <tr className="border-b border-white/10">
                    <th className="px-3 py-2 text-center">#</th>
                    <th className="px-3 py-2 text-start">{isAr ? "التاريخ" : "Date"}</th>
                    <th className="px-3 py-2 text-start">{isAr ? "البيان" : "Description"}</th>
                    <th className="px-3 py-2 text-end">{isAr ? "المبلغ" : "Amount"}</th>
                    <th className="px-3 py-2 text-start">{isAr ? "القيد المقترح" : "Suggested entry"}</th>
                    <th className="px-3 py-2 text-center">{isAr ? "المرفق" : "Attachment"}</th>
                    <th className="px-3 py-2 text-start">{isAr ? "الحالة" : "Status"}</th>
                  </tr>
                </thead>
                <tbody>
                  {bulkPreviews.map(item => {
                    const result = bulkResults[item.key];
                    const alreadyPosted = posted[item.key];
                    const status = alreadyPosted
                      ? (isAr ? `مرحّل: ${alreadyPosted.move_name || "Odoo"}` : `Posted: ${alreadyPosted.move_name || "Odoo"}`)
                      : result?.message || item.warning || (isAr ? "جاهز" : "Ready");
                    const statusClass = alreadyPosted || result?.status === "success"
                      ? "text-emerald-300"
                      : result?.status === "error" || item.warning
                        ? "text-rose-300"
                        : result?.status === "pending"
                          ? "text-amber-300"
                          : "text-cyan-200";
                    return (
                      <tr key={item.key} className="border-b border-white/5 align-top hover:bg-white/5">
                        <td className="px-3 py-2 text-center font-mono text-white/45">{item.row.row_number}</td>
                        <td className="px-3 py-2 font-mono text-white/65">{item.row.date || "—"}</td>
                        <td className="px-3 py-2 text-white">{firstLine(item.row.main_description || item.row.description || "—", 110)}</td>
                        <td className="px-3 py-2 text-end font-mono text-amber-300">{fmt(item.row.amount)} SAR</td>
                        <td className="px-3 py-2 text-white/70">
                          {item.lines.map((line, idx) => (
                            <div key={idx} className="mb-1 rounded border border-white/5 bg-black/20 px-2 py-1">
                              <span className="font-bold text-white">{line.account_label}</span>
                              <span className="ms-2 text-emerald-300">D {fmt(line.debit)}</span>
                              <span className="ms-2 text-rose-300">C {fmt(line.credit)}</span>
                            </div>
                          ))}
                        </td>
                        <td className="px-3 py-2 text-center text-amber-200">{item.attachment ? `📎 ${firstLine(item.attachment.name, 24)}` : "—"}</td>
                        <td className={`px-3 py-2 font-bold ${statusClass}`}>{status}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 p-4">
              <p className="text-xs text-white/50">{isAr ? "سيتم تجاوز القيود المرحّلة سابقًا، وسيتم تسجيل أي خطأ أمام الصف نفسه بدون إيقاف باقي القيود." : "Already posted rows are skipped. Errors are shown per row without stopping the remaining entries."}</p>
              <div className="flex gap-2">
                <button disabled={bulkPosting} onClick={() => setBulkOpen(false)} className="rounded-lg border border-white/10 px-4 py-2 text-sm text-white/70 hover:text-white disabled:opacity-40">{isAr ? "إغلاق" : "Close"}</button>
                <button disabled={bulkPosting || bulkReadyCount === 0} onClick={postAllRows} className="rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-4 py-2 text-sm font-bold text-emerald-200 hover:bg-emerald-500/25 disabled:opacity-40">{bulkPosting ? (isAr ? "جاري ترحيل كافة القيود..." : "Posting all entries...") : `🚀 ${isAr ? "ترحيل كافة القيود" : "Post all entries"}`}</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {preview && (
        <div className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/70 p-4" onClick={() => setPreview(null)}>
          <div className="max-h-[88vh] w-full max-w-4xl overflow-auto rounded-2xl border border-white/15 bg-zinc-950 p-5 shadow-2xl" onClick={event => event.stopPropagation()}>
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h3 className="text-lg font-bold text-white">👁️🚀 {isAr ? "عرض ثم ترحيل القيد" : "Preview then post journal entry"}</h3>
                <p className="mt-1 text-xs text-white/50">{isAr ? "راجع القيد والمستند المرفق قبل إنشاء القيد في Odoo. إذا وجدت ضريبة قيمة مضافة في البيان ستظهر كسطر مستقل." : "Review the entry and attached document before creating it in Odoo. If VAT is detected in the statement, it appears as a separate line."}</p>
              </div>
              <button onClick={() => setPreview(null)} className="rounded-lg border border-white/10 px-3 py-1 text-white/70 hover:text-white">✕</button>
            </div>
            {preview.warning && <div className={`mb-3 rounded-xl border px-3 py-2 text-xs ${preview.warning.includes("تم إنشاء") || preview.warning.includes("Created") ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-200" : "border-amber-500/40 bg-amber-500/15 text-amber-200"}`}>{preview.warning}</div>}
            <div className="mb-3 grid gap-2 md:grid-cols-5 text-xs">
              <div className="rounded-xl border border-white/10 bg-black/30 p-3"><div className="text-white/40">{isAr ? "التاريخ" : "Date"}</div><div className="font-bold text-white">{preview.row.date || "—"}</div></div>
              <div className="rounded-xl border border-white/10 bg-black/30 p-3"><div className="text-white/40">{isAr ? "الصف" : "Row"}</div><div className="font-bold text-white">{preview.row.row_number}</div></div>
              <div className="rounded-xl border border-white/10 bg-black/30 p-3"><div className="text-white/40">{isAr ? "المبلغ" : "Amount"}</div><div className="font-bold text-amber-300">{fmt(preview.row.amount)} SAR</div></div>
              <div className="rounded-xl border border-white/10 bg-black/30 p-3"><div className="text-white/40">{isAr ? "المرجع" : "Reference"}</div><div className="font-bold text-white">{preview.payload.ref}</div></div>
              <div className="rounded-xl border border-white/10 bg-black/30 p-3"><div className="text-white/40">{isAr ? "المستند" : "Attachment"}</div><div className="font-bold text-white">{preview.attachment ? `📎 ${firstLine(preview.attachment.name, 35)}` : (isAr ? "لا يوجد" : "None")}</div></div>
            </div>
            <div className="overflow-auto rounded-xl border border-white/10">
              <table className="w-full min-w-[720px] text-xs">
                <thead className="bg-white/5 text-white/50"><tr><th className="px-3 py-2 text-start">{isAr ? "الحساب" : "Account"}</th><th className="px-3 py-2 text-end">{isAr ? "مدين" : "Debit"}</th><th className="px-3 py-2 text-end">{isAr ? "دائن" : "Credit"}</th><th className="px-3 py-2 text-start">{isAr ? "الشريك / التحليلي" : "Partner / Analytic"}</th><th className="px-3 py-2 text-start">{isAr ? "البيان" : "Label"}</th></tr></thead>
                <tbody>{preview.lines.map((line, idx) => <tr key={idx} className="border-t border-white/5"><td className="px-3 py-2 text-white">{line.account_label}</td><td className="px-3 py-2 text-end font-mono text-emerald-300">{fmt(line.debit)}</td><td className="px-3 py-2 text-end font-mono text-rose-300">{fmt(line.credit)}</td><td className="px-3 py-2 text-white/60">{line.partner_label || "—"}{line.analytic_account_label ? ` / ${line.analytic_account_label}` : ""}</td><td className="px-3 py-2 text-white/60">{line.name}</td></tr>)}</tbody>
              </table>
            </div>
            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <button onClick={() => setPreview(null)} className="rounded-lg border border-white/10 px-4 py-2 text-sm text-white/70 hover:text-white">{isAr ? "إغلاق" : "Close"}</button>
              <button disabled={(Boolean(preview.warning) && !preview.warning?.includes("تم إنشاء") && !preview.warning?.includes("Created")) || posting[preview.key] || Boolean(posted[preview.key])} onClick={() => postRow(preview.row)} className="rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-4 py-2 text-sm font-bold text-emerald-200 hover:bg-emerald-500/25 disabled:opacity-40">{posting[preview.key] ? (isAr ? "جاري الترحيل..." : "Posting...") : posted[preview.key] ? "✅" : `🚀 ${isAr ? "ترحيل القيد إلى Odoo" : "Post entry to Odoo"}`}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
