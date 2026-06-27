"use client";

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { useLanguage } from "@/lib/LanguageContext";
import { API_BASE_URL } from "@/lib/api";

const DEFAULT_ROWS = 25;
const DEFAULT_COLS = 10;

// Convert column index to letter (0 -> A, 1 -> B, etc.)
const getColLetter = (index: number): string => {
  let letter = "";
  let temp = index;
  while (temp >= 0) {
    letter = String.fromCharCode((temp % 26) + 65) + letter;
    temp = Math.floor(temp / 26) - 1;
  }
  return letter;
};

interface OdooAccount {
  id: number;
  code: string;
  name: string;
  account_type: string;
}

interface OdooPartner {
  id: number;
  name: string;
}

interface OdooAnalyticAccount {
  id: number;
  name: string;
}

interface Worksheet {
  id: string;
  name: string;
  gridData: string[][];
  rowCount: number;
  colCount: number;
}

const normalizeLookupValue = (value: string): string =>
  value.trim().replace(/\s+/g, " ").toLowerCase();

const ARABIC_DIACRITICS_REGEX = /[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]/g;
const NON_ALNUM_REGEX = /[^a-z0-9\u0600-\u06FF\s]/g;
const ARABIC_TO_LATIN_MAP: Record<string, string> = {
  ا: "a", أ: "a", إ: "i", آ: "a", ء: "a", ؤ: "o", ئ: "e",
  ب: "b", ت: "t", ث: "th", ج: "j", ح: "h", خ: "kh",
  د: "d", ذ: "th", ر: "r", ز: "z", س: "s", ش: "sh",
  ص: "s", ض: "d", ط: "t", ظ: "z", ع: "a", غ: "gh",
  ف: "f", ق: "q", ك: "k", ل: "l", م: "m", ن: "n",
  ه: "h", ة: "a", و: "w", ي: "y", ى: "a",
};

const normalizePartnerName = (value: string): string => {
  return (value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(ARABIC_DIACRITICS_REGEX, "")
    .replace(/ـ/g, "")
    .replace(/[أإآ]/g, "ا")
    .replace(/ى/g, "ي")
    .replace(/ة/g, "ه")
    .replace(NON_ALNUM_REGEX, " ")
    .replace(/\b(company|co|corp|corporation|inc|ltd|llc|est)\b/g, " ")
    .replace(/(?:شركة|مؤسسه|مؤسسة|مكتب|مقاولات|التجارية|العامه|العامة)/g, " ")
    .replace(/\s+/g, " ")
    .trim();
};

const transliterateArabicToLatin = (value: string): string => {
  return Array.from(value || "")
    .map((ch) => ARABIC_TO_LATIN_MAP[ch] ?? ch)
    .join("")
    .replace(/\s+/g, " ")
    .trim();
};

const buildBigrams = (value: string): string[] => {
  const cleaned = value.replace(/\s+/g, " ").trim();
  if (cleaned.length < 2) return cleaned ? [cleaned] : [];
  const grams: string[] = [];
  for (let i = 0; i < cleaned.length - 1; i++) {
    grams.push(cleaned.slice(i, i + 2));
  }
  return grams;
};

const diceCoefficient = (a: string, b: string): number => {
  if (!a || !b) return 0;
  if (a === b) return 1;
  const aBigrams = buildBigrams(a);
  const bBigrams = buildBigrams(b);
  if (!aBigrams.length || !bBigrams.length) return 0;
  const aCounts = new Map<string, number>();
  aBigrams.forEach((gram) => aCounts.set(gram, (aCounts.get(gram) ?? 0) + 1));
  let overlap = 0;
  for (const gram of bBigrams) {
    const count = aCounts.get(gram) ?? 0;
    if (count > 0) {
      overlap += 1;
      aCounts.set(gram, count - 1);
    }
  }
  return (2 * overlap) / (aBigrams.length + bBigrams.length);
};

const tokenOverlapScore = (a: string, b: string): number => {
  if (!a || !b) return 0;
  const aTokens = new Set(a.split(" ").filter(Boolean));
  const bTokens = new Set(b.split(" ").filter(Boolean));
  if (!aTokens.size || !bTokens.size) return 0;
  let overlap = 0;
  aTokens.forEach((token) => {
    if (bTokens.has(token)) overlap += 1;
  });
  return overlap / Math.max(aTokens.size, bTokens.size);
};

const partnerSimilarityScore = (queryRaw: string, candidateRaw: string): number => {
  const query = normalizePartnerName(queryRaw);
  const candidate = normalizePartnerName(candidateRaw);
  if (!query || !candidate) return 0;
  if (query === candidate) return 1;

  const containsBoost =
    candidate.includes(query) || query.includes(candidate) ? 0.15 : 0;
  const nativeScore =
    (diceCoefficient(query, candidate) * 0.7) +
    (tokenOverlapScore(query, candidate) * 0.3);

  const queryLatin = transliterateArabicToLatin(query);
  const candidateLatin = transliterateArabicToLatin(candidate);
  const crossLingualScore =
    (diceCoefficient(queryLatin, candidateLatin) * 0.65) +
    (tokenOverlapScore(queryLatin, candidateLatin) * 0.35);

  return Math.min(1, Math.max(nativeScore, crossLingualScore) + containsBoost);
};

export default function DocumentIntelligencePage() {
  const { t, language } = useLanguage();
  
  // Worksheets State
  const [sheets, setSheets] = useState<Worksheet[]>(() => [
    {
      id: "sheet-1",
      name: language === "ar" ? "ورقة 1" : "Sheet1",
      gridData: Array.from({ length: DEFAULT_ROWS }, () => Array(DEFAULT_COLS).fill("")),
      rowCount: DEFAULT_ROWS,
      colCount: DEFAULT_COLS,
    }
  ]);
  const [activeSheetId, setActiveSheetId] = useState("sheet-1");
  const [renameSheetId, setRenameSheetId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  
  // Get active worksheet details
  const activeSheet = sheets.find((s) => s.id === activeSheetId) || sheets[0];
  const { gridData, rowCount, colCount } = activeSheet;

  // Cell Selection States
  const [activeCell, setActiveCell] = useState<{ r: number; c: number } | null>(null);
  const [selectionRange, setSelectionRange] = useState<{
    startR: number;
    startC: number;
    endR: number;
    endC: number;
  } | null>(null);
  
  // Cell Editing States
  const [editCell, setEditCell] = useState<{ r: number; c: number } | null>(null);
  const [editValue, setEditValue] = useState("");
  
  // Drag Selection Flag
  const [isSelecting, setIsSelecting] = useState(false);
  const [dragStart, setDragStart] = useState<{ r: number; c: number } | null>(null);
  
  // Odoo Structural Data
  const [accounts, setAccounts] = useState<OdooAccount[]>([]);
  const [partners, setPartners] = useState<OdooPartner[]>([]);
  const [analyticAccounts, setAnalyticAccounts] = useState<OdooAnalyticAccount[]>([]);
  const [, setLoadingKB] = useState(false);
  
  // Odoo Submission Modal States
  const [showOdooModal, setShowOdooModal] = useState(false);
  const [previewLines, setPreviewLines] = useState<{
    account_id: number;
    account_name: string;
    account_code: string;
    debit: number;
    credit: number;
    name: string;
    partner_name: string;
    partner_id: number | null;
    analytic_account_id: number | null;
    analytic_account_name: string;
  }[]>([]);
  const [isRegistering, setIsRegistering] = useState(false);
  const [partnerDropdownRowIndex, setPartnerDropdownRowIndex] = useState<number | null>(null);
  const [accountDropdownRowIndex, setAccountDropdownRowIndex] = useState<number | null>(null);
  const [analyticDropdownRowIndex, setAnalyticDropdownRowIndex] = useState<number | null>(null);
  const [accountSearchQuery, setAccountSearchQuery] = useState("");
  const [partnerSearchQuery, setPartnerSearchQuery] = useState("");
  const [analyticSearchQuery, setAnalyticSearchQuery] = useState("");
  const [customDate, setCustomDate] = useState("");
  const [customRef, setCustomRef] = useState("");
  const [customJournal, setCustomJournal] = useState("");
  const [showManualInputModal, setShowManualInputModal] = useState(false);
  const [manualInputText, setManualInputText] = useState("");
  const [isParsingText, setIsParsingText] = useState(false);

  const handleParseManualText = async () => {
    if (!manualInputText.trim() || isParsingText) return;
    setIsParsingText(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/erp/parse-manual-text`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          text: manualInputText,
        }),
      });

      if (!res.ok) {
        throw new Error(await res.text());
      }

      const data = await res.json();
      if (data.status === "error") {
        throw new Error(data.message);
      }

      if (data.lines && data.lines.length > 0) {
        setPreviewLines(
          data.lines.map((line: any) => ({
            ...line,
            analytic_account_id: line.analytic_account_id ?? null,
            analytic_account_name: line.analytic_account_name || "",
          }))
        );
        setCustomDate(data.date || "");
        setCustomRef(data.ref || "");
        setCustomJournal(data.journal || "");
        setShowManualInputModal(false);
        setShowOdooModal(true);
      } else {
        alert(
          language === "ar"
            ? "لم نتمكن من استخراج أي قيود محاسبية من النص المدخل. يرجى التأكد من كتابتها بشكل صحيح."
            : "No journal entry lines could be parsed from the text. Please ensure the format is correct."
        );
      }
    } catch (err: any) {
      console.error(err);
      alert(
        (language === "ar" ? "فشل تحليل النص: " : "Failed to parse text: ") +
          (err.message || err)
      );
    } finally {
      setIsParsingText(false);
    }
  };

  // Journals States
  const [journals, setJournals] = useState<{ id: number; code: string; name: string; type: string }[]>([]);
  const [selectedJournalId, setSelectedJournalId] = useState<number | null>(null);
  const [journalsLoading, setJournalsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const gridTableRef = useRef<HTMLTableElement>(null);
  const editInputRef = useRef<HTMLInputElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);
  const chatMessagesEndRef = useRef<HTMLDivElement>(null);
  const chatFileInputRef = useRef<HTMLInputElement>(null);

  // Chat States
  const [chatMessages, setChatMessages] = useState<{ role: "user" | "assistant"; text: string }[]>(() => [
    {
      role: "assistant",
      text: language === "ar" 
        ? "مرحباً بك! أنا مساعد تنظيم وتنسيق الجداول المحاسبية. اكتب لي ما تريده من تعديلات أو تنسيق (مثال: 'نظم كقيد رواتب') وسأقوم بتعديل الشبكة لك." 
        : "Hello! I am your spreadsheet layout assistant. Tell me what formatting or layout you want (e.g. 'format as payroll entry') and I will modify the grid for you."
    }
  ]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);

  // Auto scroll chat to bottom
  useEffect(() => {
    if (chatMessagesEndRef.current) {
      chatMessagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [chatMessages]);

  const handleSendChatMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!chatInput.trim() || chatLoading) return;

    const userMsg = chatInput.trim();
    setChatInput("");
    setChatMessages((prev) => [...prev, { role: "user", text: userMsg }]);
    setChatLoading(true);

    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/erp/chat-spreadsheet`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          prompt: userMsg,
          sheets: sheets.map(s => ({
            id: s.id,
            name: s.name,
            gridData: s.gridData,
            rowCount: s.rowCount,
            colCount: s.colCount,
          })),
          active_sheet_id: activeSheetId,
        }),
      });

      if (!res.ok) {
        throw new Error(await res.text());
      }

      const data = await res.json();
      
      // Add agent's response to message feed
      if (data.message) {
        setChatMessages((prev) => [...prev, { role: "assistant", text: data.message }]);
      }

      // Synchronize states
      setSheets((prevSheets) => {
        let updated = [...prevSheets];

        // 1. Handle Active Sheet Grid Data Update
        if (data.grid_data && Array.isArray(data.grid_data)) {
          updated = updated.map((s) => {
            if (s.id !== activeSheetId) return s;
            const newGrid = data.grid_data;
            const newRowCount = newGrid.length;
            const newColCount = newGrid[0]?.length || 0;
            return {
              ...s,
              gridData: newGrid,
              rowCount: newRowCount,
              colCount: newColCount,
            };
          });
        }

        // 2. Handle Rename Active Sheet
        if (data.active_sheet_name) {
          updated = updated.map((s) => 
            s.id === activeSheetId ? { ...s, name: data.active_sheet_name } : s
          );
        }

        // 3. Handle Create Sheet
        if (data.create_sheet && data.create_sheet.name) {
          const newId = `sheet-${Date.now()}`;
          const newGrid = data.create_sheet.grid_data || Array.from({ length: DEFAULT_ROWS }, () => Array(DEFAULT_COLS).fill(""));
          const rowCount = newGrid.length;
          const colCount = newGrid[0]?.length || 0;
          
          updated.push({
            id: newId,
            name: data.create_sheet.name,
            gridData: newGrid,
            rowCount,
            colCount,
          });
          // Set active sheet to the newly created one
          setTimeout(() => setActiveSheetId(newId), 50);
        }

        // 4. Handle Delete Sheet
        if (data.delete_sheet_id) {
          if (updated.length > 1) {
            const idToDelete = data.delete_sheet_id;
            updated = updated.filter((s) => s.id !== idToDelete);
            if (activeSheetId === idToDelete) {
              setActiveSheetId(updated[updated.length - 1].id);
            }
          }
        }

        return updated;
      });

    } catch (err: any) {
      console.error(err);
      setChatMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: language === "ar" 
            ? `عذراً، فشل الاتصال بالمساعد: ${err.message || err}` 
            : `Sorry, failed to connect to the assistant: ${err.message || err}`,
        },
      ]);
    } finally {
      setChatLoading(false);
    }
  };

  const handleChatFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Reset input value to allow uploading same file again
    e.target.value = "";

    setIsUploading(true);
    setChatLoading(true);

    setChatMessages((prev) => [
      ...prev,
      {
        role: "user",
        text: language === "ar"
          ? `📎 [مرفق] تم اختيار الملف: ${file.name}`
          : `📎 [Attachment] Selected file: ${file.name}`
      },
      {
        role: "assistant",
        text: language === "ar"
          ? `جاري رفع وتحليل المستند "${file.name}"...`
          : `Uploading and analyzing document "${file.name}"...`
      }
    ]);

    try {
      // 1. Upload to /api/v1/erp/upload-documents
      const formData = new FormData();
      formData.append("files", file);

      const uploadRes = await fetch(`${API_BASE_URL}/api/v1/erp/upload-documents`, {
        method: "POST",
        body: formData,
      });

      if (!uploadRes.ok) {
        throw new Error(await uploadRes.text());
      }

      const uploadData = await uploadRes.json();
      if (uploadData.error_count > 0 || !uploadData.results || uploadData.results.length === 0) {
        throw new Error(uploadData.results?.[0]?.message || "Upload failed");
      }

      const analysisResult = uploadData.results[0].result;
      const fields = analysisResult.fields || {};
      const amount = fields.total_amount || fields.amount || 0;
      const partnerName = fields.supplier_name || fields.partner_name || "";
      const rawText = analysisResult.raw_text_preview || "";

      // 2. Call /api/v1/erp/propose-transaction
      const selectedJournal = journals.find((j) => j.id === selectedJournalId);
      const docClass = selectedJournal ? selectedJournal.type : "general";

      const proposePayload = {
        filename: file.name,
        document_class: docClass,
        amount: amount,
        date: new Date().toISOString().slice(0, 10),
        partner_name: partnerName,
        raw_text: rawText,
      };

      const proposeRes = await fetch(`${API_BASE_URL}/api/v1/erp/propose-transaction`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(proposePayload),
      });

      if (!proposeRes.ok) {
        throw new Error(await proposeRes.text());
      }

      const proposeData = await proposeRes.json();
      if (proposeData.status !== "success" || !proposeData.lines) {
        throw new Error(proposeData.message || "Failed to generate proposed lines");
      }

      const proposedLines = proposeData.lines;

      // 3. Clear and populate active sheet gridData
      setSheets((prevSheets) => {
        return prevSheets.map((s) => {
          if (s.id !== activeSheetId) return s;

          const newGrid = Array.from({ length: DEFAULT_ROWS }, () => Array(DEFAULT_COLS).fill(""));

          // Set Headers
          newGrid[0][0] = language === "ar" ? "رمز الحساب" : "Account Code";
          newGrid[0][1] = language === "ar" ? "البيان / الوصف" : "Description";
          newGrid[0][2] = language === "ar" ? "مدين" : "Debit";
          newGrid[0][3] = language === "ar" ? "دائن" : "Credit";
          newGrid[0][4] = language === "ar" ? "اسم الشريك" : "Partner";
          newGrid[0][5] = language === "ar" ? "الحساب التحليلي" : "Analytic Account";

          proposedLines.forEach((line: any, idx: number) => {
            const rIdx = idx + 1;
            if (rIdx >= DEFAULT_ROWS) return;

            const accName = line.account_name || "";
            const accCode = line.account_code || accName.match(/^(\d+)/)?.[1] || accName;

            newGrid[rIdx][0] = accCode;
            newGrid[rIdx][1] = line.name || "";
            newGrid[rIdx][2] = line.debit > 0 ? String(line.debit) : "";
            newGrid[rIdx][3] = line.credit > 0 ? String(line.credit) : "";
            newGrid[rIdx][4] = line.partner_name || proposeData.suggested_partner_name || partnerName || "";
            newGrid[rIdx][5] = line.analytic_account_name || "";
          });

          return {
            ...s,
            gridData: newGrid,
            rowCount: newGrid.length,
            colCount: newGrid[0]?.length || DEFAULT_COLS,
          };
        });
      });

      setChatMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: language === "ar"
            ? `✅ تم بنجاح تحليل المستند ومطابقته مع اليومية المحددة.\n\nتم تعبئة البيانات في الجدول بالقيم المحللة:\n- القيمة: ${amount.toLocaleString()} ر.س\n- الشريك المقترح: ${proposeData.suggested_partner_name || partnerName || "غير محدد"}\n- نوع القيد: ${proposeData.journal_name}`
            : `✅ Successfully analyzed and matched document with the selected journal.\n\nSpreadsheet has been populated:\n- Amount: ${amount.toLocaleString()} SAR\n- Suggested Partner: ${proposeData.suggested_partner_name || partnerName || "N/A"}\n- Entry Type: ${proposeData.journal_name}`
        }
      ]);

    } catch (err: any) {
      console.error(err);
      setChatMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: language === "ar"
            ? `❌ فشل تحليل أو معالجة المستند: ${err.message || err}`
            : `❌ Failed to analyze or process the document: ${err.message || err}`
        }
      ]);
    } finally {
      setIsUploading(false);
      setChatLoading(false);
    }
  };

  // Load accounts and partners from Odoo Discovery on mount
  useEffect(() => {
    fetchDiscoveryData();
  }, []);

  const fetchDiscoveryData = async () => {
    setLoadingKB(true);
    setJournalsLoading(true);
    try {
      const resKB = await fetch(`${API_BASE_URL}/api/v1/erp/discovery`);
      if (resKB.ok) {
        const data = await resKB.json();
        if (data.accounts) {
          setAccounts(data.accounts);
        }
      }
      const resPartners = await fetch(`${API_BASE_URL}/api/v1/erp/partners`);
      if (resPartners.ok) {
        const pData = await resPartners.json();
        setPartners(pData);
      }
      const resAnalytic = await fetch(`${API_BASE_URL}/api/v1/erp/analytic-accounts`);
      if (resAnalytic.ok) {
        const aData = await resAnalytic.json();
        setAnalyticAccounts(aData);
      } else {
        setAnalyticAccounts([]);
      }

      // Fetch Journals
      try {
        const resJournals = await fetch(`${API_BASE_URL}/api/v1/erp/journals`);
        if (resJournals.ok) {
          const jData = await resJournals.json();
          setJournals(jData);
          if (jData.length > 0) {
            const defaultJournal = jData.find((j: any) => j.type === "general") || jData[0];
            setSelectedJournalId(defaultJournal.id);
          }
        } else {
          // Fallback static journals
          const defaultJournals = [
            { id: 1, code: "MISC", name: "Miscellaneous Operations", type: "general" },
            { id: 2, code: "BILL", name: "Vendor Bills", type: "purchase" },
            { id: 3, code: "INV", name: "Customer Invoices", type: "sale" },
            { id: 4, code: "BNK1", name: "Bank", type: "bank" }
          ];
          setJournals(defaultJournals);
          setSelectedJournalId(1);
        }
      } catch (jErr) {
        console.error("Failed to fetch Odoo journals, using static fallbacks:", jErr);
        const defaultJournals = [
          { id: 1, code: "MISC", name: "Miscellaneous Operations", type: "general" },
          { id: 2, code: "BILL", name: "Vendor Bills", type: "purchase" },
          { id: 3, code: "INV", name: "Customer Invoices", type: "sale" },
          { id: 4, code: "BNK1", name: "Bank", type: "bank" }
        ];
        setJournals(defaultJournals);
        setSelectedJournalId(1);
      }
    } catch (err) {
      console.error("Failed to fetch Odoo discovery info:", err);
    } finally {
      setLoadingKB(false);
      setJournalsLoading(false);
    }
  };

  const resolveAccountFromValue = (rawValue: string): OdooAccount | null => {
    const normalizedValue = normalizeLookupValue(rawValue);
    if (!normalizedValue) return null;

    const extractedCode = rawValue.trim().match(/^\d[\d.\-]*/)?.[0] || "";

    return (
      accounts.find((acc) => normalizeLookupValue(acc.code) === normalizedValue) ||
      (extractedCode ? accounts.find((acc) => acc.code === extractedCode) : undefined) ||
      accounts.find((acc) => normalizeLookupValue(`${acc.code} ${acc.name}`) === normalizedValue) ||
      accounts.find((acc) => normalizeLookupValue(acc.name) === normalizedValue) ||
      accounts.find((acc) => {
        const accountCode = normalizeLookupValue(acc.code);
        const accountName = normalizeLookupValue(acc.name);
        const accountLabel = normalizeLookupValue(`${acc.code} ${acc.name}`);

        return (
          accountLabel.includes(normalizedValue) ||
          normalizedValue.includes(accountLabel) ||
          accountName.includes(normalizedValue) ||
          normalizedValue.includes(accountName) ||
          accountCode.includes(normalizedValue) ||
          normalizedValue.includes(accountCode)
        );
      }) ||
      null
    );
  };

  const resolvePartnerFromValue = (rawValue: string): OdooPartner | null => {
    const normalizedValue = normalizePartnerName(rawValue);
    if (!normalizedValue) return null;

    let bestMatch: OdooPartner | null = null;
    let bestScore = 0;

    for (const partner of partners) {
      if (!partner || !partner.name || typeof partner.name !== "string") continue;
      const score = partnerSimilarityScore(rawValue, partner.name);
      if (score > bestScore) {
        bestScore = score;
        bestMatch = partner;
      }
    }

    return bestMatch && bestScore >= 0.5 ? bestMatch : null;
  };

  const getPartnerCandidates = (query: string): OdooPartner[] => {
    if (!query.trim()) return partners;
    return partners
      .map((partner) => ({
        partner,
        score: partnerSimilarityScore(query, partner.name || ""),
      }))
      .filter((item) => item.score >= 0.35)
      .sort((a, b) => b.score - a.score)
      .map((item) => item.partner);
  };

  // Helper to ensure input is fully visible in cell
  useEffect(() => {
    if (editCell && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editCell]);

  // Focus rename input on open
  useEffect(() => {
    if (renameSheetId && renameInputRef.current) {
      renameInputRef.current.focus();
      renameInputRef.current.select();
    }
  }, [renameSheetId]);

  // Reset selection states when active sheet changes
  useEffect(() => {
    setActiveCell(null);
    setSelectionRange(null);
    setEditCell(null);
  }, [activeSheetId]);

  // Excel Cell Selection Range Highlights
  const isCellSelected = (r: number, c: number) => {
    if (!selectionRange) return false;
    const { startR, startC, endR, endC } = selectionRange;
    const minR = Math.min(startR, endR);
    const maxR = Math.max(startR, endR);
    const minC = Math.min(startC, endC);
    const maxC = Math.max(startC, endC);
    return r >= minR && r <= maxR && c >= minC && c <= maxC;
  };

  const isCellSelectionBorder = (r: number, c: number) => {
    if (!selectionRange) return { top: false, bottom: false, left: false, right: false };
    const { startR, startC, endR, endC } = selectionRange;
    const minR = Math.min(startR, endR);
    const maxR = Math.max(startR, endR);
    const minC = Math.min(startC, endC);
    const maxC = Math.max(startC, endC);
    
    return {
      top: r === minR && isCellSelected(r, c),
      bottom: r === maxR && isCellSelected(r, c),
      left: c === minC && isCellSelected(r, c),
      right: c === maxC && isCellSelected(r, c),
    };
  };

  const handleCellMouseDown = (r: number, c: number, e: React.MouseEvent) => {
    if (editCell && (editCell.r !== r || editCell.c !== c)) {
      commitEdit();
    }
    
    if (e.shiftKey && activeCell) {
      setSelectionRange({
        startR: activeCell.r,
        startC: activeCell.c,
        endR: r,
        endC: c,
      });
    } else {
      setActiveCell({ r, c });
      setSelectionRange({ startR: r, startC: c, endR: r, endC: c });
      setIsSelecting(true);
      setDragStart({ r, c });
    }
  };

  const handleCellMouseEnter = (r: number, c: number) => {
    if (isSelecting && dragStart) {
      setSelectionRange({
        startR: dragStart.r,
        startC: dragStart.c,
        endR: r,
        endC: c,
      });
    }
  };

  const handleCellMouseUp = () => {
    setIsSelecting(false);
  };

  // Keyboard navigation and editing shortcuts
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!activeCell) return;
    const { r, c } = activeCell;

    if (editCell) {
      if (e.key === "Enter") {
        e.preventDefault();
        commitEdit();
        if (r < rowCount - 1) {
          const nextR = r + 1;
          setActiveCell({ r: nextR, c });
          setSelectionRange({ startR: nextR, startC: c, endR: nextR, endC: c });
        }
      } else if (e.key === "Escape") {
        setEditCell(null);
      } else if (e.key === "Tab") {
        e.preventDefault();
        commitEdit();
        if (e.shiftKey) {
          if (c > 0) {
            const prevC = c - 1;
            setActiveCell({ r, c: prevC });
            setSelectionRange({ startR: r, startC: prevC, endR: r, endC: prevC });
          }
        } else {
          if (c < colCount - 1) {
            const nextC = c + 1;
            setActiveCell({ r, c: nextC });
            setSelectionRange({ startR: r, startC: nextC, endR: r, endC: nextC });
          }
        }
      }
      return;
    }

    if (e.key === "Enter") {
      e.preventDefault();
      setEditCell({ r, c });
      setEditValue(gridData[r][c]);
      return;
    }

    if (e.key === "ArrowUp") {
      e.preventDefault();
      if (r > 0) {
        const nextR = r - 1;
        setActiveCell({ r: nextR, c });
        setSelectionRange({ startR: nextR, startC: c, endR: nextR, endC: c });
      }
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (r < rowCount - 1) {
        const nextR = r + 1;
        setActiveCell({ r: nextR, c });
        setSelectionRange({ startR: nextR, startC: c, endR: nextR, endC: c });
      }
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      const moveLeft = language === "ar" ? c < colCount - 1 : c > 0;
      const step = language === "ar" ? 1 : -1;
      if (moveLeft) {
        const nextC = c + step;
        setActiveCell({ r, c: nextC });
        setSelectionRange({ startR: r, startC: nextC, endR: r, endC: nextC });
      }
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      const moveRight = language === "ar" ? c > 0 : c < colCount - 1;
      const step = language === "ar" ? -1 : 1;
      if (moveRight) {
        const nextC = c + step;
        setActiveCell({ r, c: nextC });
        setSelectionRange({ startR: r, startC: nextC, endR: r, endC: nextC });
      }
    } else if (e.key === "Tab") {
      e.preventDefault();
      if (e.shiftKey) {
        if (c > 0) {
          const prevC = c - 1;
          setActiveCell({ r, c: prevC });
          setSelectionRange({ startR: r, startC: prevC, endR: r, endC: prevC });
        }
      } else {
        if (c < colCount - 1) {
          const nextC = c + 1;
          setActiveCell({ r, c: nextC });
          setSelectionRange({ startR: r, startC: nextC, endR: r, endC: nextC });
        }
      }
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      clearSelectionContents();
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "c") {
      e.preventDefault();
      copySelectionToClipboard();
    } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      setEditCell({ r, c });
      setEditValue(e.key);
    }
  };

  const commitEdit = () => {
    if (!editCell) return;
    const { r, c } = editCell;
    setSheets((prev) =>
      prev.map((s) => {
        if (s.id !== activeSheetId) return s;
        const copy = s.gridData.map((row) => [...row]);
        copy[r][c] = editValue;
        return { ...s, gridData: copy };
      })
    );
    setEditCell(null);
  };

  const clearSelectionContents = () => {
    if (!selectionRange) return;
    const { startR, startC, endR, endC } = selectionRange;
    const minR = Math.min(startR, endR);
    const maxR = Math.max(startR, endR);
    const minC = Math.min(startC, endC);
    const maxC = Math.max(startC, endC);

    setSheets((prev) =>
      prev.map((s) => {
        if (s.id !== activeSheetId) return s;
        const copy = s.gridData.map((row) => [...row]);
        for (let r = minR; r <= maxR; r++) {
          for (let c = minC; c <= maxC; c++) {
            copy[r][c] = "";
          }
        }
        return { ...s, gridData: copy };
      })
    );
  };

  // TSV Copy Clipboard Integration
  const copySelectionToClipboard = () => {
    if (!selectionRange) return;
    const { startR, startC, endR, endC } = selectionRange;
    const minR = Math.min(startR, endR);
    const maxR = Math.max(startR, endR);
    const minC = Math.min(startC, endC);
    const maxC = Math.max(startC, endC);

    const rowsText: string[] = [];
    for (let r = minR; r <= maxR; r++) {
      const colsText: string[] = [];
      for (let c = minC; c <= maxC; c++) {
        colsText.push(gridData[r][c]);
      }
      rowsText.push(colsText.join("\t"));
    }
    const tsvText = rowsText.join("\n");
    navigator.clipboard.writeText(tsvText);
  };

  // TSV Paste Clipboard Integration
  const handlePaste = (e: React.ClipboardEvent) => {
    const target = e.target as HTMLElement;
    if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) {
      return;
    }
    e.preventDefault();
    if (!activeCell) return;
    const { r, c } = activeCell;
    
    const pasteText = e.clipboardData.getData("text/plain");
    const rows = pasteText.split(/\r?\n/);
    if (rows.length === 0 || (rows.length === 1 && rows[0] === "")) return;
    
    const parsedGrid = rows.map((row) => row.split("\t"));
    
    const maxRowNeeded = r + parsedGrid.length;
    const maxColNeeded = c + Math.max(...parsedGrid.map((row) => row.length));

    setSheets((prev) =>
      prev.map((s) => {
        if (s.id !== activeSheetId) return s;

        const currentHeight = Math.max(s.rowCount, maxRowNeeded);
        const currentWidth = Math.max(s.colCount, maxColNeeded);
        
        const copy = Array.from({ length: currentHeight }, (_, rIdx) => {
          const row = s.gridData[rIdx] || [];
          return Array.from({ length: currentWidth }, (_, cIdx) => row[cIdx] || "");
        });

        for (let rOffset = 0; rOffset < parsedGrid.length; rOffset++) {
          for (let cOffset = 0; cOffset < parsedGrid[rOffset].length; cOffset++) {
            const targetR = r + rOffset;
            const targetC = c + cOffset;
            copy[targetR][targetC] = parsedGrid[rOffset][cOffset];
          }
        }

        return {
          ...s,
          gridData: copy,
          rowCount: currentHeight,
          colCount: currentWidth,
        };
      })
    );

    setSelectionRange({
      startR: r,
      startC: c,
      endR: r + parsedGrid.length - 1,
      endC: c + parsedGrid[0].length - 1,
    });
  };

  // Grid Controls Toolbar Actions
  const handleAddRow = () => {
    setSheets((prev) =>
      prev.map((s) => {
        if (s.id !== activeSheetId) return s;
        const newRows = s.rowCount + 1;
        const copy = s.gridData.map((row) => [...row]);
        copy.push(Array(s.colCount).fill(""));
        return { ...s, rowCount: newRows, gridData: copy };
      })
    );
  };

  const handleDeleteRow = () => {
    if (rowCount <= 1) return;
    setSheets((prev) =>
      prev.map((s) => {
        if (s.id !== activeSheetId) return s;
        return {
          ...s,
          rowCount: s.rowCount - 1,
          gridData: s.gridData.slice(0, -1),
        };
      })
    );
  };

  const handleAddCol = () => {
    setSheets((prev) =>
      prev.map((s) => {
        if (s.id !== activeSheetId) return s;
        const newCols = s.colCount + 1;
        const copy = s.gridData.map((row) => [...row, ""]);
        return { ...s, colCount: newCols, gridData: copy };
      })
    );
  };

  const handleDeleteCol = () => {
    if (colCount <= 1) return;
    setSheets((prev) =>
      prev.map((s) => {
        if (s.id !== activeSheetId) return s;
        return {
          ...s,
          colCount: s.colCount - 1,
          gridData: s.gridData.map((row) => row.slice(0, -1)),
        };
      })
    );
  };

  const handleClearSheet = () => {
    if (
      confirm(
        language === "ar"
          ? "هل أنت متأكد من مسح جميع بيانات ورقة العمل الحالية؟"
          : "Are you sure you want to clear the active sheet data?"
      )
    ) {
      setSheets((prev) =>
        prev.map((s) => {
          if (s.id !== activeSheetId) return s;
          return {
            ...s,
            gridData: Array.from({ length: s.rowCount }, () => Array(s.colCount).fill("")),
          };
        })
      );
      setActiveCell(null);
      setSelectionRange(null);
    }
  };

  // Export to CSV File Download
  const handleExportCSV = () => {
    const csvRows: string[] = [];
    for (let r = 0; r < rowCount; r++) {
      const row = gridData[r].map((val) => {
        const escaped = val.replace(/"/g, '""');
        return `"${escaped}"`;
      });
      csvRows.push(row.join(","));
    }
    const csvContent = "\ufeff" + csvRows.join("\n"); // Add BOM for Excel Arabic encoding support
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", `${activeSheet.name}_export_${new Date().toISOString().slice(0, 10)}.csv`);
    link.style.visibility = "hidden";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // Submit to Odoo Parsing Logic
  const handlePrepareOdooSubmission = () => {
    let codeCol = -1;
    let labelCol = -1;
    let debitCol = -1;
    let creditCol = -1;
    let partnerCol = -1;
    let analyticCol = -1;
    let dateCol = -1;
    let refCol = -1;
    let journalCol = -1;

    let startR = 0;
    let endR = rowCount - 1;
    let startC = 0;
    let endC = colCount - 1;

    // Detect if we should use the active selection range (if covering multiple cells)
    const hasSelection = selectionRange && 
      (selectionRange.endR - selectionRange.startR >= 1) && 
      (selectionRange.endC - selectionRange.startC >= 1);

    if (hasSelection) {
      startR = selectionRange.startR;
      endR = selectionRange.endR;
      startC = selectionRange.startC;
      endC = selectionRange.endC;
    }

    const firstRowInRange = gridData[startR];
    let isHeaderRow = false;
    for (let c = startC; c <= endC; c++) {
      const val = (firstRowInRange[c] || "").toLowerCase().trim();
      if (
        val.includes("حساب") || val.includes("مدين") || val.includes("دائن") || val.includes("شريك") ||
        val.includes("code") || val.includes("debit") || val.includes("credit") || val.includes("partner") ||
        val.includes("date") || val.includes("التاريخ") || val.includes("ref") || val.includes("journal") ||
        val.includes("البيان") || val.includes("وصف") || val.includes("description") || val.includes("name") ||
        val === "الاسم" || val === "الأسم"
      ) {
        isHeaderRow = true;
        break;
      }
    }

    let startRowIndex = startR;
    if (isHeaderRow) {
      startRowIndex = startR + 1;
      for (let c = startC; c <= endC; c++) {
        const val = (firstRowInRange[c] || "").toLowerCase().trim();
        if (val.includes("رمز") || val.includes("code") || val.includes("حساب") || val.includes("account")) {
          codeCol = c;
        } else if (val.includes("بيان") || val.includes("label") || val.includes("وصف") || val.includes("description") || val.includes("name") || val === "الاسم" || val === "الأسم") {
          labelCol = c;
        } else if (val.includes("مدين") || val.includes("debit")) {
          debitCol = c;
        } else if (val.includes("دائن") || val.includes("credit")) {
          creditCol = c;
        } else if (val.includes("شريك") || val.includes("partner") || val.includes("مورد") || val.includes("عميل")) {
          partnerCol = c;
        } else if (val.includes("تحليلي") || val.includes("analytic") || val.includes("مركز تكلفة") || val.includes("cost center")) {
          analyticCol = c;
        } else if (val.includes("التاريخ") || val.includes("date")) {
          dateCol = c;
        } else if (val.includes("رقم") || val.includes("ref") || val.includes("move") || val.includes("قيد")) {
          refCol = c;
        } else if (val.includes("دفتر") || val.includes("journal") || val.includes("يومية")) {
          journalCol = c;
        }
      }
    } else {
      // Look at main header row 0
      const mainHeaderRow = gridData[0];
      mainHeaderRow.forEach((val, index) => {
        const norm = val.toLowerCase().trim();
        if (norm.includes("رمز") || norm.includes("code") || norm.includes("حساب") || norm.includes("account")) {
          codeCol = index;
        } else if (norm.includes("بيان") || norm.includes("label") || norm.includes("وصف") || norm.includes("description") || norm.includes("name") || norm === "الاسم" || norm === "الأسم") {
          labelCol = index;
        } else if (norm.includes("مدين") || norm.includes("debit")) {
          debitCol = index;
        } else if (norm.includes("دائن") || norm.includes("credit")) {
          creditCol = index;
        } else if (norm.includes("شريك") || norm.includes("partner") || norm.includes("مورد") || norm.includes("عميل")) {
          partnerCol = index;
        } else if (norm.includes("تحليلي") || norm.includes("analytic") || norm.includes("مركز تكلفة") || norm.includes("cost center")) {
          analyticCol = index;
        } else if (norm.includes("التاريخ") || norm.includes("date")) {
          dateCol = index;
        } else if (norm.includes("رقم") || norm.includes("ref") || norm.includes("move") || norm.includes("قيد")) {
          refCol = index;
        } else if (norm.includes("دفتر") || norm.includes("journal") || norm.includes("يومية")) {
          journalCol = index;
        }
      });
      const mainHasHeader = mainHeaderRow.some((val) => {
        const norm = val.toLowerCase().trim();
        return norm.includes("حساب") || norm.includes("مدين") || norm.includes("دائن") || norm.includes("شريك") || norm.includes("code") || norm.includes("debit") || norm.includes("credit");
      });
      if (mainHasHeader && startRowIndex === 0) {
        startRowIndex = 1;
      }
    }

    // Fallbacks if columns not identified
    if (codeCol === -1) codeCol = startC;
    if (labelCol === -1) labelCol = startC + 1 <= endC ? startC + 1 : startC;
    if (debitCol === -1) debitCol = startC + 2 <= endC ? startC + 2 : startC;
    if (creditCol === -1) creditCol = startC + 3 <= endC ? startC + 3 : startC;
    if (partnerCol === -1) partnerCol = startC + 4 <= endC ? startC + 4 : startC;
    if (analyticCol === -1 && startC + 5 <= endC) analyticCol = startC + 5;

    const lines: typeof previewLines = [];
    let extractedDate = "";
    let extractedRef = "";
    let extractedJournal = "";

    for (let r = startRowIndex; r <= endR; r++) {
      const row = gridData[r];
      if (!row) continue;

      const accountCellValue = (row[codeCol] || "").trim();
      const code = accountCellValue;
      const debitVal = parseFloat((row[debitCol] || "").replace(/,/g, "")) || 0;
      const creditVal = parseFloat((row[creditCol] || "").replace(/,/g, "")) || 0;
      const label = (row[labelCol] || "").trim() || (language === "ar" ? "قيد محاسبي تفاعلي" : "Manual Spreadsheet Entry");
      const partnerName = (row[partnerCol] || "").trim();
      const analyticName = analyticCol !== -1 ? (row[analyticCol] || "").trim() : "";

      if (dateCol !== -1 && row[dateCol] && !extractedDate) {
        extractedDate = row[dateCol].trim();
      }
      if (refCol !== -1 && row[refCol] && !extractedRef) {
        extractedRef = row[refCol].trim();
      }
      if (journalCol !== -1 && row[journalCol] && !extractedJournal) {
        extractedJournal = row[journalCol].trim();
      }

      if (!code && debitVal === 0 && creditVal === 0) {
        continue;
      }

      const matchedAcc = resolveAccountFromValue(accountCellValue);

      let resolvedPartnerId: number | null = null;
      let resolvedPartnerName = partnerName;
      if (partnerName) {
        const matchedPartner = resolvePartnerFromValue(partnerName);
        if (matchedPartner) {
          resolvedPartnerId = matchedPartner.id;
          resolvedPartnerName = matchedPartner.name;
        }
      }

      let resolvedAnalyticId: number | null = null;
      let resolvedAnalyticName = analyticName;
      if (analyticName) {
        const matchedAnalytic = analyticAccounts.find((a) =>
          a && a.name && typeof a.name === "string" && a.name.toLowerCase().includes(analyticName.toLowerCase())
        );
        if (matchedAnalytic) {
          resolvedAnalyticId = matchedAnalytic.id;
          resolvedAnalyticName = matchedAnalytic.name;
        }
      }

      lines.push({
        account_id: matchedAcc ? matchedAcc.id : 0,
        account_name: matchedAcc ? `${matchedAcc.code} ${matchedAcc.name}` : (accountCellValue ? `${accountCellValue} (غير معرف)` : "حساب غير محدد"),
        account_code: matchedAcc ? matchedAcc.code : accountCellValue,
        debit: debitVal,
        credit: creditVal,
        name: label,
        partner_name: resolvedPartnerName,
        partner_id: resolvedPartnerId,
        analytic_account_id: resolvedAnalyticId,
        analytic_account_name: resolvedAnalyticName,
      });
    }

    if (lines.length < 2) {
      alert(
        language === "ar"
          ? "يجب تحديد سطرين محاسبيين على الأقل للتسجيل."
          : "Please select/enter at least 2 journal lines to register."
      );
      return;
    }

    setPreviewLines(lines);
    setCustomDate(extractedDate);
    setCustomRef(extractedRef);
    const selectedJournal = journals.find((j) => j.id === selectedJournalId);
    setCustomJournal(extractedJournal || (selectedJournal ? selectedJournal.code : ""));
    setShowOdooModal(true);
  };

  const handleUpdateLineAccount = (rowIndex: number, account: OdooAccount) => {
    setPreviewLines((prev) =>
      prev.map((line, idx) =>
        idx === rowIndex
          ? {
              ...line,
              account_id: account.id,
              account_name: `${account.code} ${account.name}`,
              account_code: account.code,
            }
          : line
      )
    );
    setAccountDropdownRowIndex(null);
  };

  const handleUpdateLinePartner = (rowIndex: number, partner: OdooPartner | null) => {
    setPreviewLines((prev) =>
      prev.map((line, idx) =>
        idx === rowIndex
          ? {
              ...line,
              partner_id: partner ? partner.id : null,
              partner_name: partner ? partner.name : "",
            }
          : line
      )
    );
    setPartnerDropdownRowIndex(null);
  };

  const handleUpdateLineAnalytic = (rowIndex: number, analytic: OdooAnalyticAccount | null) => {
    setPreviewLines((prev) =>
      prev.map((line, idx) =>
        idx === rowIndex
          ? {
              ...line,
              analytic_account_id: analytic ? analytic.id : null,
              analytic_account_name: analytic ? analytic.name : "",
            }
          : line
      )
    );
    setAnalyticDropdownRowIndex(null);
  };

  const executeOdooRegistration = async () => {
    const totalDebit = previewLines.reduce((acc, curr) => acc + curr.debit, 0);
    const totalCredit = previewLines.reduce((acc, curr) => acc + curr.credit, 0);

    if (Math.abs(totalDebit - totalCredit) > 0.01) {
      alert(t("excel.unbalanced") || "Unbalanced entry! Debit and Credit totals must match.");
      return;
    }

    const invalidAcc = previewLines.find((l) => l.account_id === 0);
    if (invalidAcc) {
      alert(
        language === "ar"
          ? "يرجى تحديد حساب محاسبي معرف لجميع القيود قبل المتابعة."
          : "Please resolve/select valid Odoo accounts for all lines before submitting."
      );
      return;
    }

    setIsRegistering(true);
    try {
      const payload = {
        filename: `spreadsheet_entry_${new Date().toISOString().slice(0, 10)}.pdf`,
        document_class: customJournal || "general_journal",
        amount: totalDebit,
        date: customDate || new Date().toISOString().slice(0, 10),
        partner_name: previewLines[0]?.partner_name || "",
        partner_id: previewLines[0]?.partner_id || null,
        ref: customRef || `Manual Excel Entry ${new Date().toLocaleDateString()}`,
        raw_text: JSON.stringify(previewLines),
        lines: previewLines.map((l) => ({
          account_id: l.account_id,
          account_code: l.account_code,
          account_name: l.account_name,
          debit: l.debit,
          credit: l.credit,
          name: l.name,
          partner_id: l.partner_id,
          analytic_account_id: l.analytic_account_id,
          analytic_account_name: l.analytic_account_name,
        })),
      };

      const res = await fetch(`${API_BASE_URL}/api/v1/erp/register-document`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        throw new Error(await res.text());
      }

      alert(t("excel.successPost") || "Successfully registered in Odoo!");
      setShowOdooModal(false);
    } catch (err: any) {
      console.error(err);
      alert((t("excel.errorPost") || "Failed to register:") + " " + err.message);
    } finally {
      setIsRegistering(false);
    }
  };

  // Worksheets Tab Methods
  const handleAddSheet = () => {
    const newId = `sheet-${Date.now()}`;
    const newNumber = sheets.length + 1;
    const newSheetName = language === "ar" ? `ورقة ${newNumber}` : `Sheet${newNumber}`;
    
    setSheets((prev) => [
      ...prev,
      {
        id: newId,
        name: newSheetName,
        gridData: Array.from({ length: DEFAULT_ROWS }, () => Array(DEFAULT_COLS).fill("")),
        rowCount: DEFAULT_ROWS,
        colCount: DEFAULT_COLS,
      }
    ]);
    setActiveSheetId(newId);
  };

  const handleDeleteSheet = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (sheets.length <= 1) return;

    if (
      confirm(
        language === "ar"
          ? "هل أنت متأكد من حذف ورقة العمل هذه بالكامل؟ لا يمكن التراجع عن هذا الإجراء."
          : "Are you sure you want to delete this worksheet? This action cannot be undone."
      )
    ) {
      setSheets((prev) => prev.filter((s) => s.id !== id));
      if (activeSheetId === id) {
        const remaining = sheets.filter((s) => s.id !== id);
        setActiveSheetId(remaining[remaining.length - 1].id);
      }
    }
  };

  const handleStartRenameSheet = (id: string, name: string) => {
    setRenameSheetId(id);
    setRenameValue(name);
  };

  const handleCommitRenameSheet = () => {
    if (!renameSheetId || !renameValue.trim()) {
      setRenameSheetId(null);
      return;
    }
    setSheets((prev) =>
      prev.map((s) => (s.id === renameSheetId ? { ...s, name: renameValue.trim() } : s))
    );
    setRenameSheetId(null);
  };

  // Edit dropdown state
  const [showEditMenu, setShowEditMenu] = useState(false);
  const editMenuRef = useRef<HTMLDivElement>(null);

  // Close edit menu on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (editMenuRef.current && !editMenuRef.current.contains(e.target as Node)) {
        setShowEditMenu(false);
      }
    }
    if (showEditMenu) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [showEditMenu]);

  // Calculations for cells layout
  const gridRows = Array.from({ length: rowCount }, (_, r) => r);
  const gridCols = Array.from({ length: colCount }, (_, c) => c);
  
  const totalDebitPrv = previewLines.reduce((sum, item) => sum + item.debit, 0);
  const totalCreditPrv = previewLines.reduce((sum, item) => sum + item.credit, 0);
  const isBalanced = Math.abs(totalDebitPrv - totalCreditPrv) <= 0.01;

  return (
    <div
      ref={containerRef}
      className="wood-shell fade-in p-6 h-screen overflow-hidden flex flex-row gap-6 justify-start"
      onPaste={handlePaste}
    >
      {/* Left Column: Spreadsheet Content */}
      <div className="flex-1 flex flex-col h-full overflow-hidden">
        {/* Title */}
        <div className="flex justify-between items-center mb-4">
          <div className="flex flex-col">
            <h1 className="text-xl font-bold text-white tracking-wide">
              {t("excel.title")}
            </h1>
            <p className="text-[10px] text-white/50 mt-0.5">
              {t("excel.subtitle")}
            </p>
          </div>

          {/* Back Link */}
          <Link
            href="/team"
            className="text-xs font-bold text-[#d9a441]/80 hover:text-[#d9a441] transition-all flex items-center gap-1 cursor-pointer"
          >
            {language === "ar" ? "← " + t("excel.backToTeam") : t("excel.backToTeam") + " →"}
          </Link>
        </div>

        {/* Spreadsheet Action Toolbar — simplified */}
        <div className="flex items-center gap-2 mb-3 p-2 bg-black/40 border border-white/10 rounded-xl select-none">
          {/* Edit Grid dropdown */}
          <div className="relative" ref={editMenuRef}>
            <button
              onClick={() => setShowEditMenu(!showEditMenu)}
              className="h-8 px-3 rounded-lg border border-white/15 hover:border-white/30 text-white/80 hover:text-white text-[11px] font-semibold transition-all hover:bg-white/5 flex items-center gap-1.5 cursor-pointer"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
              </svg>
              {t("excel.editMenu")}
              <svg className={`w-3 h-3 transition-transform ${showEditMenu ? "rotate-180" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>

            {showEditMenu && (
              <div className="absolute top-9 right-0 z-40 w-48 bg-[#1b0d04] border border-white/15 rounded-xl shadow-2xl py-1 text-[11px]">
                <button onClick={() => { handleAddRow(); setShowEditMenu(false); }} className="w-full text-right px-3 py-2 hover:bg-white/5 text-white/80 hover:text-white flex items-center gap-2 cursor-pointer transition-colors">
                  <svg className="w-3.5 h-3.5 text-[#d9a441]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
                  {t("excel.addRow")}
                </button>
                <button onClick={() => { handleDeleteRow(); setShowEditMenu(false); }} className="w-full text-right px-3 py-2 hover:bg-white/5 text-white/80 hover:text-white flex items-center gap-2 cursor-pointer transition-colors">
                  <svg className="w-3.5 h-3.5 text-red-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="5" y1="12" x2="19" y2="12" /></svg>
                  {t("excel.deleteRow")}
                </button>
                <div className="h-[1px] bg-white/10 my-1" />
                <button onClick={() => { handleAddCol(); setShowEditMenu(false); }} className="w-full text-right px-3 py-2 hover:bg-white/5 text-white/80 hover:text-white flex items-center gap-2 cursor-pointer transition-colors">
                  <svg className="w-3.5 h-3.5 text-[#d9a441]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
                  {t("excel.addColumn")}
                </button>
                <button onClick={() => { handleDeleteCol(); setShowEditMenu(false); }} className="w-full text-right px-3 py-2 hover:bg-white/5 text-white/80 hover:text-white flex items-center gap-2 cursor-pointer transition-colors">
                  <svg className="w-3.5 h-3.5 text-red-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="5" y1="12" x2="19" y2="12" /></svg>
                  {t("excel.deleteColumn")}
                </button>
                <div className="h-[1px] bg-white/10 my-1" />
                <button onClick={() => { handleClearSheet(); setShowEditMenu(false); }} className="w-full text-right px-3 py-2 hover:bg-red-500/10 text-red-400 hover:text-red-300 flex items-center gap-2 cursor-pointer transition-colors">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
                  {t("excel.clearGrid")}
                </button>
              </div>
            )}
          </div>

          {/* Operation Type Dropdown */}
          <div className="flex items-center gap-1.5 border border-white/10 rounded-lg px-2.5 bg-black/30 h-8">
            <span className="text-[10px] text-white/50 font-medium">
              {language === "ar" ? "اليومية:" : "Journal:"}
            </span>
            {journalsLoading ? (
              <span className="text-[10px] text-white/40 animate-pulse">...</span>
            ) : (
              <select
                value={selectedJournalId || ""}
                onChange={(e) => {
                  const val = e.target.value ? parseInt(e.target.value) : null;
                  setSelectedJournalId(val);
                }}
                className="bg-transparent border-none outline-none text-white/80 text-[11px] font-medium cursor-pointer focus:ring-0 focus:outline-none"
              >
                {journals.map((journal) => (
                  <option key={journal.id} value={journal.id} className="bg-[#1b0d04] text-white">
                    {journal.name} ({journal.code})
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Export CSV — icon-only with tooltip */}
          <button
            onClick={handleExportCSV}
            title={t("excel.exportCSV")}
            className="h-8 w-8 rounded-lg border border-white/10 hover:border-white/25 text-white/60 hover:text-white hover:bg-white/5 flex items-center justify-center cursor-pointer transition-all"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
          </button>

          <div className="flex-1" />

          {/* Manual Entry */}
          <button
            onClick={() => {
              setManualInputText("");
              setShowManualInputModal(true);
            }}
            className="h-8 px-3 rounded-lg border border-white/15 hover:border-[#d9a441]/50 text-white/70 hover:text-[#d9a441] text-[11px] font-semibold transition-all hover:bg-[#d9a441]/5 flex items-center gap-1.5 cursor-pointer"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z" />
            </svg>
            {t("excel.manualEntry")}
          </button>

          {/* Submit to Odoo — primary CTA */}
          <button
            onClick={handlePrepareOdooSubmission}
            className="h-8 px-4 rounded-lg bg-gradient-to-r from-amber-500 to-yellow-600 hover:from-amber-600 hover:to-yellow-700 text-black text-[11px] font-bold shadow-md hover:shadow-lg transition-all flex items-center gap-1.5 cursor-pointer active:scale-[0.98]"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12" />
            </svg>
            {t("excel.submitOdoo")}
          </button>
        </div>

        {/* Grid Container */}
        <div
          className="flex-1 overflow-auto border border-gray-300 rounded-t-xl bg-white relative"
          onMouseUp={handleCellMouseUp}
        >
          <table
            ref={gridTableRef}
            onKeyDown={handleKeyDown}
            tabIndex={0}
            className="border-collapse table-fixed w-max min-w-full text-xs font-mono outline-none select-none text-right text-gray-800"
            dir={language === "ar" ? "rtl" : "ltr"}
          >
            {/* Header Row */}
            <thead>
              <tr className="bg-[#f3f3f3] sticky top-0 z-20 border-b border-gray-300">
                <th className="w-10 h-7 border-l border-gray-300 text-center text-[10px] text-gray-400 sticky right-0 z-30 bg-[#f3f3f3]" />
                {gridCols.map((c) => (
                  <th
                    key={c}
                    className="w-32 h-7 border-l border-gray-300 text-center font-bold text-[10.5px] text-gray-600 bg-[#f3f3f3] hover:bg-gray-200 transition-colors"
                  >
                    {getColLetter(c)}
                    {c === 0 && <div className="text-[8.5px] font-normal text-[#107c41] font-semibold">{language === "ar" ? "رمز الحساب" : "Account Code"}</div>}
                    {c === 1 && <div className="text-[8.5px] font-normal text-[#107c41] font-semibold">{language === "ar" ? "البيان / الوصف" : "Description"}</div>}
                    {c === 2 && <div className="text-[8.5px] font-normal text-[#107c41] font-semibold">{language === "ar" ? "مدين" : "Debit"}</div>}
                    {c === 3 && <div className="text-[8.5px] font-normal text-[#107c41] font-semibold">{language === "ar" ? "دائن" : "Credit"}</div>}
                    {c === 4 && <div className="text-[8.5px] font-normal text-[#107c41] font-semibold">{language === "ar" ? "اسم الشريك" : "Partner"}</div>}
                    {c === 5 && (
                      <div className="text-[8.5px] font-normal text-[#107c41] font-semibold flex items-center justify-center gap-1">
                        <svg className="w-2.5 h-2.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M4 6h16M4 12h10M4 18h7" strokeLinecap="round" />
                          <circle cx="18" cy="12" r="3" />
                        </svg>
                        <span>{language === "ar" ? "حساب تحليلي" : "Analytic Account"}</span>
                      </div>
                    )}
                  </th>
                ))}
              </tr>
            </thead>

            {/* Grid Rows */}
            <tbody>
              {gridRows.map((r) => (
                <tr key={r} className="border-b border-gray-200 h-7 hover:bg-gray-50 bg-white">
                  <td className="border-l border-gray-300 text-center text-[10px] font-bold text-gray-500 bg-[#f3f3f3] sticky right-0 z-10">
                    {r + 1}
                  </td>
                  
                  {gridCols.map((c) => {
                    const val = gridData[r][c];
                    const active = activeCell?.r === r && activeCell?.c === c;
                    const editing = editCell?.r === r && editCell?.c === c;
                    const selected = isCellSelected(r, c);
                    const borders = isCellSelectionBorder(r, c);

                    let cellClass = "px-2 border-l border-gray-200 relative align-middle cursor-cell transition-all select-none ";
                    
                    if (editing) {
                      cellClass += "p-0 z-10 bg-white text-gray-900";
                    } else if (active) {
                      cellClass += "bg-[#e6f2eb]";
                    } else if (selected) {
                      cellClass += "bg-[#e2f0d9]";
                    } else {
                      cellClass += "bg-white text-gray-800";
                    }

                    const borderStyle: React.CSSProperties = {};
                    if (selected && !editing) {
                      const activeColor = "#107c41"; // Excel signature green
                      if (borders.top) borderStyle.borderTop = `2px solid ${activeColor}`;
                      if (borders.bottom) borderStyle.borderBottom = `2px solid ${activeColor}`;
                      if (borders.left) borderStyle.borderLeft = `2px solid ${activeColor}`;
                      if (borders.right) borderStyle.borderRight = `2px solid ${activeColor}`;
                    }

                    return (
                      <td
                        key={c}
                        className={cellClass}
                        style={borderStyle}
                        onMouseDown={(e) => handleCellMouseDown(r, c, e)}
                        onMouseEnter={() => handleCellMouseEnter(r, c)}
                        onDoubleClick={() => {
                          setEditCell({ r, c });
                          setEditValue(val);
                        }}
                      >
                        {editing ? (
                          <input
                            ref={editInputRef}
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            onBlur={commitEdit}
                            className="w-full h-full bg-white text-gray-900 border-2 border-[#107c41] px-1.5 focus:outline-none text-right font-mono"
                          />
                        ) : (
                          <div className={`truncate w-full max-w-[124px] pr-0.5 ${c === 5 && val ? "inline-flex items-center gap-1 text-[#107c41] font-semibold" : ""}`}>
                            {c === 5 && val && (
                              <svg className="w-3 h-3 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M4 6h16M4 12h10M4 18h7" strokeLinecap="round" />
                                <circle cx="18" cy="12" r="3" />
                              </svg>
                            )}
                            <span className="truncate">{val}</span>
                          </div>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Worksheets Tabs Bar (Bottom of grid) */}
        <div className="flex bg-[#f3f3f3] border-x border-b border-gray-300 p-1 rounded-b-xl items-center overflow-x-auto select-none gap-1 h-9">
          {sheets.map((sheet) => {
            const isActive = sheet.id === activeSheetId;
            const isRename = sheet.id === renameSheetId;

            return (
              <div
                key={sheet.id}
                onClick={() => !isRename && setActiveSheetId(sheet.id)}
                onDoubleClick={() => handleStartRenameSheet(sheet.id, sheet.name)}
                className={`h-7 px-3.5 rounded-md text-[10.5px] font-bold flex items-center gap-2 transition-all cursor-pointer border ${
                  isActive
                    ? "bg-white border-b-2 border-b-[#107c41] border-x border-gray-300 text-[#107c41] shadow-[0_1px_3px_rgba(0,0,0,0.05)]"
                    : "bg-[#e1e1e1] border-transparent hover:bg-gray-200 text-gray-600 hover:text-gray-900"
                }`}
              >
                {isRename ? (
                  <input
                    ref={renameInputRef}
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.target.value)}
                    onBlur={handleCommitRenameSheet}
                    onKeyDown={(e) => e.key === "Enter" && handleCommitRenameSheet()}
                    className="bg-white text-gray-900 border border-[#107c41] px-1 text-center font-bold text-[10.5px] w-20 rounded"
                  />
                ) : (
                  <span>{sheet.name}</span>
                )}

                {/* Close delete button */}
                {sheets.length > 1 && (
                  <span
                    onClick={(e) => handleDeleteSheet(sheet.id, e)}
                    className="hover:bg-red-500/20 hover:text-red-400 w-3.5 h-3.5 rounded-full flex items-center justify-center text-[11px] transition-colors font-normal"
                    title={language === "ar" ? "حذف ورقة العمل" : "Delete Worksheet"}
                  >
                    ×
                  </span>
                )}
              </div>
            );
          })}

          {/* Add Tab Button */}
          <button
            onClick={handleAddSheet}
            className="w-7 h-7 rounded-md bg-[#e1e1e1] hover:bg-gray-200 text-gray-600 hover:text-gray-900 border border-gray-300 flex items-center justify-center font-bold text-xs cursor-pointer transition-all"
            title={language === "ar" ? "إضافة ورقة عمل جديدة" : "Add New Worksheet"}
          >
            ＋
          </button>
        </div>

        {/* Copy-Paste Instructions Footer */}
        <div className="mt-3 flex justify-between text-[9px] text-white/50 px-1">
          <span>💡 {language === "ar" ? "اضغط نقرًا مزدوجًا أو اضغط Enter للتعديل على الخلية. انقر مزدوجًا على اسم الورقة لإعادة تسميتها." : "Double click/Enter to edit cell. Double click tab name to rename."}</span>
          <span>📋 {language === "ar" ? "يدعم نسخ ولصق الخلايا مباشرة من وإلى إكسيل (Ctrl+C / Ctrl+V)." : "Supports copy/paste from and to Excel (Ctrl+C / Ctrl+V)."}</span>
        </div>
      </div>

      {/* Right Column: AI Chat Panel */}
      <div className="w-80 md:w-96 bg-black/35 border border-white/10 rounded-2xl p-4 flex flex-col h-full overflow-hidden text-right shadow-2xl backdrop-blur-md" dir="rtl">
        <div className="border-b border-white/10 pb-3 mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-2.5 h-2.5 rounded-full bg-[#107c41] shadow-[0_0_8px_#107c41]" />
            <h2 className="text-sm font-bold text-white tracking-wide">
              {language === "ar" ? "مساعد التنسيق الذكي" : "Smart Layout Assistant"}
            </h2>
          </div>
          <span className="text-[9px] font-bold bg-[#107c41]/10 text-[#2ecc71] border border-[#107c41]/30 px-2 py-0.5 rounded-full">AI AGENT</span>
        </div>

        {/* Messages feed */}
        <div className="flex-1 overflow-y-auto mb-3 flex flex-col gap-3.5 pr-1">
          {chatMessages.map((msg, idx) => (
            <div
              key={idx}
              className={`max-w-[85%] p-3 rounded-2xl text-[11.5px] leading-relaxed shadow-sm transition-all ${
                msg.role === "user"
                  ? "bg-[#107c41]/10 border border-[#107c41]/25 text-white self-end rounded-br-none"
                  : "bg-white/10 border border-white/5 text-white/90 self-start rounded-bl-none"
              }`}
            >
              <div className="whitespace-pre-line">{msg.text}</div>
            </div>
          ))}
          {chatLoading && (
            <div className="bg-white/5 border border-white/5 text-white/70 self-start p-3 rounded-2xl rounded-bl-none max-w-[85%] flex items-center gap-2 text-[11px] animate-pulse">
              <svg className="animate-spin h-4 w-4 text-[#107c41]" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
              <span>{language === "ar" ? "جاري التنسيق..." : "Formatting..."}</span>
            </div>
          )}
          <div ref={chatMessagesEndRef} />
        </div>

        {/* Chat input form */}
        <form onSubmit={handleSendChatMessage} className="flex gap-2 bg-black/40 border border-white/10 rounded-xl p-1.5 focus-within:border-[#107c41]/50 focus-within:shadow-[0_0_8px_rgba(16,124,65,0.15)] transition-all">
          <button
            type="button"
            onClick={() => chatFileInputRef.current?.click()}
            disabled={chatLoading || isUploading}
            className="h-7 w-7 rounded-lg border border-[#d9a441]/30 hover:border-[#d9a441] text-[#d9a441] hover:bg-[#d9a441]/10 flex items-center justify-center cursor-pointer transition-all disabled:opacity-40 disabled:cursor-not-allowed text-[14px]"
            title={language === "ar" ? "إرفاق مستند وتحليله" : "Attach & analyze document"}
          >
            📎
          </button>
          
          <input
            type="file"
            ref={chatFileInputRef}
            onChange={handleChatFileChange}
            accept=".pdf,.png,.jpg,.jpeg,.xlsx,.xls,.csv"
            className="hidden"
          />

          <input
            type="text"
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            placeholder={language === "ar" ? "اكتب توجيهات التنسيق..." : "Write layout instructions..."}
            disabled={chatLoading || isUploading}
            className="flex-1 bg-transparent border-none outline-none text-white text-xs px-2 focus:ring-0 placeholder-white/30 text-right font-sans"
            dir="rtl"
          />
          <button
            type="submit"
            disabled={chatLoading || isUploading || !chatInput.trim()}
            className="h-7 px-3.5 bg-gradient-to-r from-[#107c41] to-[#1ebd60] hover:from-[#1ebd60] hover:to-[#107c41] text-white rounded-lg font-bold text-[10.5px] transition-all flex items-center justify-center cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed shadow-md"
          >
            {language === "ar" ? "أرسل" : "Send"}
          </button>
        </form>
      </div>

      {/* Odoo Journal Entry Proposal Modal */}
      {showOdooModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-md p-6 select-none">
          <div className="wood-panel rounded-[24px] border border-yellow-500/20 shadow-2xl w-full max-w-2xl max-h-[90%] flex flex-col overflow-hidden">
            {/* Header */}
            <div className="flex justify-between items-center px-6 py-4 border-b border-white/10 bg-black/40">
              <div className="flex flex-col">
                <h2 className="text-sm font-bold bg-gradient-to-r from-amber-300 to-yellow-500 bg-clip-text text-transparent">
                  {t("excel.odooJournalTitle")}
                </h2>
                <p className="text-[10px] text-white/50 mt-0.5">
                  {t("excel.odooJournalDesc")}
                </p>
              </div>
              <button
                onClick={() => setShowOdooModal(false)}
                className="h-6 px-2.5 rounded-full border border-white/15 hover:border-white/30 text-white/60 hover:text-white text-[10px] font-bold cursor-pointer"
              >
                {t("team.close")}
              </button>
            </div>

            {/* Scrollable Form Body */}
            <div className="flex-1 overflow-auto p-6 flex flex-col gap-5 text-right" dir={language === "ar" ? "rtl" : "ltr"}>
              
              {/* Balanced Status */}
              <div className="flex justify-between items-center bg-black/20 p-3 border border-white/5 rounded-xl text-xs">
                <div className="flex gap-4">
                  <div>
                    <span className="text-white/40">{language === "ar" ? "إجمالي المدين:" : "Total Debit:"} </span>
                    <span className="font-mono font-bold text-yellow-500">{totalDebitPrv.toLocaleString()} ر.س</span>
                  </div>
                  <div>
                    <span className="text-white/40">{language === "ar" ? "إجمالي الدائن:" : "Total Credit:"} </span>
                    <span className="font-mono font-bold text-yellow-500">{totalCreditPrv.toLocaleString()} ر.س</span>
                  </div>
                </div>

                <div className="flex items-center gap-1.5">
                  {isBalanced ? (
                    <>
                      <span className="status-dot" />
                      <span className="text-[10.5px] text-emerald-400 font-bold">{language === "ar" ? "قيد متزن" : "Balanced"}</span>
                    </>
                  ) : (
                    <>
                      <span className="w-2.5 h-2.5 rounded-full bg-red-500 shadow-[0_0_10px_rgba(239,68,68,0.8)]" />
                      <span className="text-[10.5px] text-red-400 font-bold">{language === "ar" ? "غير متزن" : "Unbalanced"}</span>
                    </>
                  )}
                </div>
              </div>

              {/* Journal Lines Table */}
              <div className="flex flex-col gap-2">
                <span className="text-[10.5px] text-white/60 font-semibold">{language === "ar" ? "قيود الحسابات المقترحة:" : "Proposed Journal Items:"}</span>
                
                <div className="border border-white/10 rounded-xl overflow-hidden bg-black/20 text-[11px]">
                  <table className="w-full text-right border-collapse">
                    <thead>
                      <tr className="bg-black/40 border-b border-white/10 text-white/50 text-[10px] h-8">
                        <th className="px-3">{language === "ar" ? "الحساب (أودو)" : "Odoo Account"}</th>
                        <th className="px-3">{language === "ar" ? "البيان" : "Description"}</th>
                        <th className="px-3 text-left">{language === "ar" ? "مدين" : "Debit"}</th>
                        <th className="px-3 text-left">{language === "ar" ? "دائن" : "Credit"}</th>
                        <th className="px-3">{language === "ar" ? "الشريك" : "Partner"}</th>
                        <th className="px-3">{language === "ar" ? "الحساب التحليلي" : "Analytic Account"}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {previewLines.map((line, rowIndex) => (
                        <tr key={rowIndex} className="border-b border-white/5 h-10 hover:bg-white/5 transition-colors">
                          
                          {/* Account Selector */}
                          <td className="px-3 relative w-48">
                            <div
                              onClick={() => {
                                if (accountDropdownRowIndex === rowIndex) {
                                  setAccountDropdownRowIndex(null);
                                } else {
                                  setAccountDropdownRowIndex(rowIndex);
                                  setPartnerDropdownRowIndex(null);
                                  setAnalyticDropdownRowIndex(null);
                                  setAccountSearchQuery("");
                                }
                              }}
                              className={`px-2 py-1 rounded border text-[10.5px] truncate cursor-pointer ${
                                line.account_id === 0 ? "border-red-500/50 bg-red-500/5 text-red-300" : "border-white/10 bg-black/40 text-white/90"
                              }`}
                            >
                              {line.account_name} ⬇️
                            </div>
                            
                            {accountDropdownRowIndex === rowIndex && (
                              <div className="absolute right-3 top-9 z-50 w-80 max-h-72 bg-[#1b0d04] border border-[#d9a441]/40 rounded-lg shadow-2xl p-1 text-right flex flex-col">
                                <div className="p-1 border-b border-white/10 flex items-center gap-1.5 bg-black/40 rounded-t-md">
                                  <span className="text-xs text-[#d9a441] pl-1">🔍</span>
                                  <input
                                    type="text"
                                    placeholder={language === "ar" ? "بحث عن حساب..." : "Search account..."}
                                    value={accountSearchQuery}
                                    onChange={(e) => setAccountSearchQuery(e.target.value)}
                                    onKeyDown={(e) => {
                                      if (e.key === "Enter") {
                                        e.preventDefault();
                                        const filtered = accounts.filter((acc) => {
                                          if (!accountSearchQuery) return true;
                                          const q = accountSearchQuery.toLowerCase();
                                          return (
                                            (acc.code && acc.code.toLowerCase().includes(q)) ||
                                            (acc.name && typeof acc.name === 'string' && acc.name.toLowerCase().includes(q))
                                          );
                                        });
                                        if (filtered.length > 0) {
                                          handleUpdateLineAccount(rowIndex, filtered[0]);
                                        }
                                      } else if (e.key === "Escape") {
                                        setAccountDropdownRowIndex(null);
                                      }
                                    }}
                                    className="w-full bg-transparent border-none text-xs text-white focus:outline-none focus:ring-0 placeholder-white/30 text-right pr-1"
                                    onClick={(e) => e.stopPropagation()}
                                    autoFocus
                                  />
                                </div>
                                <div className="overflow-y-auto max-h-56">
                                  {accounts
                                    .filter((acc) => {
                                      if (!accountSearchQuery) return true;
                                      const q = accountSearchQuery.toLowerCase();
                                      return (
                                        (acc.code && acc.code.toLowerCase().includes(q)) ||
                                        (acc.name && typeof acc.name === 'string' && acc.name.toLowerCase().includes(q))
                                      );
                                    })
                                    .map((acc) => (
                                      <div
                                        key={acc.id}
                                        onClick={() => handleUpdateLineAccount(rowIndex, acc)}
                                        className="p-2 rounded hover:bg-[#d9a441]/20 cursor-pointer text-xs border-b border-white/5 last:border-b-0 truncate text-white/80"
                                      >
                                        <span className="text-[#d9a441] font-bold font-mono mr-1">{acc.code}</span> {acc.name}
                                      </div>
                                    ))}
                                </div>
                              </div>
                            )}
                          </td>

                          {/* Description */}
                          <td className="px-3 text-white/80">{line.name}</td>

                          {/* Debit */}
                          <td className="px-3 text-left font-mono text-emerald-400 font-bold">{line.debit > 0 ? line.debit.toLocaleString() : "-"}</td>

                          {/* Credit */}
                          <td className="px-3 text-left font-mono text-amber-400 font-bold">{line.credit > 0 ? line.credit.toLocaleString() : "-"}</td>

                          {/* Partner Selector */}
                          <td className="px-3 relative w-40">
                            <div
                              onClick={() => {
                                if (partnerDropdownRowIndex === rowIndex) {
                                  setPartnerDropdownRowIndex(null);
                                } else {
                                  setPartnerDropdownRowIndex(rowIndex);
                                  setAccountDropdownRowIndex(null);
                                  setAnalyticDropdownRowIndex(null);
                                  setPartnerSearchQuery("");
                                }
                              }}
                              className="px-2 py-1 rounded border border-white/10 bg-black/40 text-[10.5px] truncate cursor-pointer text-white/80"
                            >
                              {line.partner_name || (language === "ar" ? "شريك عام" : "General Partner")} ⬇️
                            </div>

                            {partnerDropdownRowIndex === rowIndex && (
                              <div className="absolute left-3 top-9 z-50 w-72 max-h-72 bg-[#1b0d04] border border-[#d9a441]/40 rounded-lg shadow-2xl p-1 text-right flex flex-col">
                                <div className="p-1 border-b border-white/10 flex items-center gap-1.5 bg-black/40 rounded-t-md">
                                  <span className="text-xs text-[#d9a441] pl-1">🔍</span>
                                  <input
                                    type="text"
                                    placeholder={language === "ar" ? "بحث عن شريك..." : "Search partner..."}
                                    value={partnerSearchQuery}
                                    onChange={(e) => setPartnerSearchQuery(e.target.value)}
                                    onKeyDown={(e) => {
                                      if (e.key === "Enter") {
                                        e.preventDefault();
                                        const filtered = getPartnerCandidates(partnerSearchQuery);
                                        if (filtered.length > 0) {
                                          handleUpdateLinePartner(rowIndex, filtered[0]);
                                        }
                                      } else if (e.key === "Escape") {
                                        setPartnerDropdownRowIndex(null);
                                      }
                                    }}
                                    className="w-full bg-transparent border-none text-xs text-white focus:outline-none focus:ring-0 placeholder-white/30 text-right pr-1"
                                    onClick={(e) => e.stopPropagation()}
                                    autoFocus
                                  />
                                </div>
                                <div className="overflow-y-auto max-h-56">
                                  <div
                                    onClick={() => handleUpdateLinePartner(rowIndex, null)}
                                    className="p-2 rounded hover:bg-[#d9a441]/20 cursor-pointer text-xs border-b border-white/5 text-white/40 font-bold"
                                  >
                                    ❌ {language === "ar" ? "شريك عام (بدون شريك)" : "None (General)"}
                                  </div>
                                  {getPartnerCandidates(partnerSearchQuery)
                                    .map((p) => (
                                      <div
                                        key={p.id}
                                        onClick={() => handleUpdateLinePartner(rowIndex, p)}
                                        className="p-2 rounded hover:bg-[#d9a441]/20 cursor-pointer text-xs border-b border-white/5 last:border-b-0 truncate text-white/80"
                                      >
                                        {p.name}
                                      </div>
                                    ))}
                                </div>
                              </div>
                            )}
                          </td>

                          {/* Analytic Account Selector */}
                          <td className="px-3 relative w-48">
                            <div
                              onClick={() => {
                                if (analyticDropdownRowIndex === rowIndex) {
                                  setAnalyticDropdownRowIndex(null);
                                } else {
                                  setAnalyticDropdownRowIndex(rowIndex);
                                  setAccountDropdownRowIndex(null);
                                  setPartnerDropdownRowIndex(null);
                                  setAnalyticSearchQuery("");
                                }
                              }}
                              className="px-2 py-1 rounded border border-white/10 bg-black/40 text-[10.5px] truncate cursor-pointer text-white/80"
                            >
                              {line.analytic_account_name || (language === "ar" ? "بدون حساب تحليلي" : "No Analytic Account")} ⬇️
                            </div>

                            {analyticDropdownRowIndex === rowIndex && (
                              <div className="absolute left-3 top-9 z-50 w-72 max-h-72 bg-[#1b0d04] border border-[#d9a441]/40 rounded-lg shadow-2xl p-1 text-right flex flex-col">
                                <div className="p-1 border-b border-white/10 flex items-center gap-1.5 bg-black/40 rounded-t-md">
                                  <span className="text-xs text-[#d9a441] pl-1">🔍</span>
                                  <input
                                    type="text"
                                    placeholder={language === "ar" ? "بحث عن حساب تحليلي..." : "Search analytic account..."}
                                    value={analyticSearchQuery}
                                    onChange={(e) => setAnalyticSearchQuery(e.target.value)}
                                    onKeyDown={(e) => {
                                      if (e.key === "Enter") {
                                        e.preventDefault();
                                        const filtered = analyticAccounts.filter((a) => {
                                          if (!analyticSearchQuery) return true;
                                          const q = analyticSearchQuery.toLowerCase();
                                          return a && a.name && typeof a.name === "string" && a.name.toLowerCase().includes(q);
                                        });
                                        if (filtered.length > 0) {
                                          handleUpdateLineAnalytic(rowIndex, filtered[0]);
                                        }
                                      } else if (e.key === "Escape") {
                                        setAnalyticDropdownRowIndex(null);
                                      }
                                    }}
                                    className="w-full bg-transparent border-none text-xs text-white focus:outline-none focus:ring-0 placeholder-white/30 text-right pr-1"
                                    onClick={(e) => e.stopPropagation()}
                                    autoFocus
                                  />
                                </div>
                                <div className="overflow-y-auto max-h-56">
                                  <div
                                    onClick={() => handleUpdateLineAnalytic(rowIndex, null)}
                                    className="p-2 rounded hover:bg-[#d9a441]/20 cursor-pointer text-xs border-b border-white/5 text-white/40 font-bold"
                                  >
                                    ❌ {language === "ar" ? "بدون حساب تحليلي" : "None"}
                                  </div>
                                  {analyticAccounts
                                    .filter((a) => {
                                      if (!analyticSearchQuery) return true;
                                      const q = analyticSearchQuery.toLowerCase();
                                      return a && a.name && typeof a.name === "string" && a.name.toLowerCase().includes(q);
                                    })
                                    .map((a) => (
                                      <div
                                        key={a.id}
                                        onClick={() => handleUpdateLineAnalytic(rowIndex, a)}
                                        className="p-2 rounded hover:bg-[#d9a441]/20 cursor-pointer text-xs border-b border-white/5 last:border-b-0 truncate text-white/80"
                                      >
                                        {a.name}
                                      </div>
                                    ))}
                                </div>
                              </div>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            {/* Footer Buttons */}
            <div className="px-6 py-4 bg-black/40 border-t border-white/10 flex justify-end gap-3">
              <button
                onClick={() => setShowOdooModal(false)}
                className="h-9 px-4 rounded-xl border border-white/15 hover:border-white/30 text-white/70 hover:text-white font-bold text-xs cursor-pointer transition-all"
              >
                {language === "ar" ? "إلغاء" : "Cancel"}
              </button>
              <button
                onClick={executeOdooRegistration}
                disabled={isRegistering || !isBalanced || previewLines.some((l) => l.account_id === 0)}
                className="h-9 px-5 rounded-xl bg-gradient-to-br from-[#221205] to-[#0f0701] border border-green-500 text-green-400 font-bold text-xs shadow-[0_0_12px_rgba(16,185,129,0.2)] hover:shadow-[0_0_20px_rgba(16,185,129,0.5)] transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
              >
                {isRegistering ? (
                  <>
                    <svg className="animate-spin h-3.5 w-3.5 text-green-400" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                    <span>{language === "ar" ? "جاري التسجيل..." : "Registering..."}</span>
                  </>
                ) : (
                  <>
                    <span>🏢</span>
                    <span>{language === "ar" ? "تأكيد وتسجيل القيد في أودو" : "Confirm & Register in Odoo"}</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Direct Paste / Manual Entry Modal */}
      {showManualInputModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-md p-6 select-none">
          <div className="wood-panel rounded-[24px] border border-yellow-500/20 shadow-2xl w-full max-w-xl max-h-[85%] flex flex-col overflow-hidden">
            {/* Header */}
            <div className="flex justify-between items-center px-6 py-4 border-b border-white/10 bg-black/40">
              <div className="flex flex-col">
                <h2 className="text-sm font-bold bg-gradient-to-r from-amber-300 to-yellow-500 bg-clip-text text-transparent">
                  {language === "ar" ? "لصق مباشر أو كتابة يدوية للبيانات" : "Direct Paste or Manual Text Entry"}
                </h2>
                <p className="text-[10px] text-white/50 mt-0.5">
                  {language === "ar"
                    ? "الصق جدولاً من إكسيل أو اكتب تفاصيل القيود يدوياً وسيقوم النظام بفهمها ومطابقتها"
                    : "Paste a table from Excel or type details line by line, and the system will parse and resolve them"}
                </p>
              </div>
              <button
                onClick={() => setShowManualInputModal(false)}
                className="h-6 px-2.5 rounded-full border border-white/15 hover:border-white/30 text-white/60 hover:text-white text-[10px] font-bold cursor-pointer"
              >
                {t("team.close")}
              </button>
            </div>

            {/* Modal Body */}
            <div className="flex-1 p-6 flex flex-col gap-4 text-right" dir="rtl">
              <div className="text-[11px] text-[#d9a441] bg-[#d9a441]/10 border border-[#d9a441]/25 p-3.5 rounded-xl leading-relaxed">
                {language === "ar" ? (
                  <>
                    💡 <strong>طريقة الكتابة/اللصق:</strong>
                    <ul className="list-disc list-inside mt-1.5 flex flex-col gap-1 pr-2">
                      <li>تستطيع لصق صفوف جدول من إكسيل مباشرة في المربع أدناه.</li>
                      <li>أو اكتب نصاً حراً مثل: <i>&quot;التاريخ: 2026-06-07، من حساب 101001 شريك شركة الرياض مدين 5000 إلى حساب 102014 دائن 5000&quot;</i>.</li>
                    </ul>
                  </>
                ) : (
                  <>
                    💡 <strong>Format Guide:</strong>
                    <ul className="list-disc list-inside mt-1.5 flex flex-col gap-1 pl-2 text-left">
                      <li>You can paste table rows copied directly from Excel.</li>
                      <li>Or write free-text: <i>&quot;Date: 2026-06-07, Account 101001 debit 5000, Account 102014 credit 5000&quot;</i>.</li>
                    </ul>
                  </>
                )}
              </div>

              <textarea
                value={manualInputText}
                onChange={(e) => setManualInputText(e.target.value)}
                placeholder={
                  language === "ar"
                    ? "الصق أو اكتب تفاصيل القيود والجداول هنا..."
                    : "Paste or type journal details here..."
                }
                disabled={isParsingText}
                className="w-full flex-1 min-h-[200px] bg-black/40 border border-white/15 focus:border-[#d9a441]/50 rounded-xl p-3.5 text-xs text-white focus:outline-none focus:ring-0 placeholder-white/20 resize-none font-mono text-right"
              />
            </div>

            {/* Footer */}
            <div className="px-6 py-4 bg-black/40 border-t border-white/10 flex justify-end gap-3">
              <button
                onClick={() => setShowManualInputModal(false)}
                className="h-9 px-4 rounded-xl border border-white/15 hover:border-white/30 text-white/70 hover:text-white font-bold text-xs cursor-pointer transition-all"
              >
                {language === "ar" ? "إلغاء" : "Cancel"}
              </button>
              <button
                onClick={handleParseManualText}
                disabled={isParsingText || !manualInputText.trim()}
                className="h-9 px-5 rounded-xl bg-gradient-to-br from-[#221205] to-[#0f0701] border border-green-500 text-green-400 font-bold text-xs shadow-[0_0_12px_rgba(16,185,129,0.2)] hover:shadow-[0_0_20px_rgba(16,185,129,0.5)] transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
              >
                {isParsingText ? (
                  <>
                    <svg className="animate-spin h-3.5 w-3.5 text-green-400" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                    <span>{language === "ar" ? "جاري التحليل..." : "Parsing..."}</span>
                  </>
                ) : (
                  <>
                    <span>🔍</span>
                    <span>{language === "ar" ? "تحليل وتوجيه البيانات" : "Parse & Route"}</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
