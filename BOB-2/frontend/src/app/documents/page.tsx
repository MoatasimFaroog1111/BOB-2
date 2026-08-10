"use client";

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { useLanguage } from "@/lib/LanguageContext";
import { useCompany } from "@/lib/CompanyContext";
import { documentsGateway } from "@/features/documents/api/documentsGateway";
import { useDocumentDiscovery } from "@/features/documents/hooks/useDocumentDiscovery";
import {
  createEmptyGrid,
  DEFAULT_WORKSHEET_COLUMNS,
  DEFAULT_WORKSHEET_ROWS,
  useWorksheets,
} from "@/features/documents/hooks/useWorksheets";
import { ManualEntryModal } from "@/features/documents/components/ManualEntryModal";
import { OdooEntryReviewModal } from "@/features/documents/components/OdooEntryReviewModal";
import {
  normalizeLookupValue,
  normalizePartnerName,
  partnerSimilarityScore,
} from "@/features/documents/model/partnerMatching";
import type { OdooAccount, OdooAnalyticAccount, OdooPartner, PreviewJournalLine } from "@/features/documents/model/types";
import { prepareJournalEntry } from "@/features/documents/model/prepareJournalEntry";

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

export default function DocumentIntelligencePage() {
  const { t, language } = useLanguage();
  const { selectedCompanyId } = useCompany();
  
  const {
    sheets, setSheets, activeSheet, activeSheetId, setActiveSheetId,
    renameSheetId, renameValue, setRenameValue,
    addRow, deleteRow, addColumn, deleteColumn, clearActiveSheet,
    addSheet, deleteSheet, startRenaming, commitRename,
  } = useWorksheets(language);
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
  
  const {
    accounts,
    partners,
    analyticAccounts,
    journals,
    selectedJournalId,
    setSelectedJournalId,
    journalsLoading,
  } = useDocumentDiscovery(selectedCompanyId);
  
  // Odoo Submission Modal States
  const [showOdooModal, setShowOdooModal] = useState(false);
  const [previewLines, setPreviewLines] = useState<PreviewJournalLine[]>([]);
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
      const res = await documentsGateway.parseManualText({
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
      const res = await documentsGateway.chatSpreadsheet({
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
          const newGrid = data.create_sheet.grid_data || createEmptyGrid();
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
      // Upload and analyze through the feature gateway.
      const formData = new FormData();
      formData.append("files", file);

      const uploadRes = await documentsGateway.uploadDocuments({
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

      // Request a draft transaction through the feature gateway.
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

      const proposeRes = await documentsGateway.proposeTransaction({
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

          const newGrid = createEmptyGrid();

          // Set Headers
          newGrid[0][0] = language === "ar" ? "رمز الحساب" : "Account Code";
          newGrid[0][1] = language === "ar" ? "البيان / الوصف" : "Description";
          newGrid[0][2] = language === "ar" ? "مدين" : "Debit";
          newGrid[0][3] = language === "ar" ? "دائن" : "Credit";
          newGrid[0][4] = language === "ar" ? "اسم الشريك" : "Partner";
          newGrid[0][5] = language === "ar" ? "الحساب التحليلي" : "Analytic Account";

          proposedLines.forEach((line: any, idx: number) => {
            const rIdx = idx + 1;
            if (rIdx >= DEFAULT_WORKSHEET_ROWS) return;

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
            colCount: newGrid[0]?.length || DEFAULT_WORKSHEET_COLUMNS,
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

  const resolveAccountFromValue = (rawValue: string): OdooAccount | null => {
    const normalizedValue = normalizeLookupValue(rawValue);
    if (!normalizedValue) return null;

    const extractedCode = rawValue.trim().match(/^\d[\d.\-]*/)?.[0] || "";

    return (
      accounts.find((acc) => normalizeLookupValue(acc.code) === normalizedValue) ||
      (extractedCode ? accounts.find((acc) => acc.code === extractedCode) : undefined) ||
      accounts.find((acc) => normalizeLookupValue(`${acc.code} ${acc.name}`) === normalizedValue) ||
      accounts.fin