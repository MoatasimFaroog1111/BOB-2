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
  const handleAddRow = addRow;
  const handleDeleteRow = deleteRow;
  const handleAddCol = addColumn;
  const handleDeleteCol = deleteColumn;

  const handleClearSheet = () => {
    if (
      confirm(
        language === "ar"
          ? "هل أنت متأكد من مسح جميع بيانات ورقة العمل الحالية؟"
          : "Are you sure you want to clear the active sheet data?"
      )
    ) {
      clearActiveSheet();
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
    const prepared = prepareJournalEntry({
      gridData,
      rowCount,
      colCount,
      selectionRange,
      language,
      analyticAccounts,
      journals,
      selectedJournalId,
      resolveAccountFromValue,
      resolvePartnerFromValue,
    });
    if (!prepared) {
      alert(
        language === "ar"
          ? "يجب تحديد سطرين محاسبيين على الأقل للتسجيل."
          : "Please select/enter at least 2 journal lines to register."
      );
      return;
    }
    setPreviewLines(prepared.lines);
    setCustomDate(prepared.date);
    setCustomRef(prepared.reference);
    setCustomJournal(prepared.journal);
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
      const selectedJournalObj = journals.find((j) => j.id === selectedJournalId);
      const payload = {
        filename: `spreadsheet_entry_${new Date().toISOString().slice(0, 10)}.pdf`,
        document_class: customJournal || (selectedJournalObj ? selectedJournalObj.type : "general_journal"),
        journal_id: selectedJournalId,
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

      const res = await documentsGateway.registerDocument({
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
  const handleAddSheet = addSheet;

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
      deleteSheet(id);
    }
  };

  const handleStartRenameSheet = (id: string, name: string) => {
    startRenaming(id, name);
  };

  const handleCommitRenameSheet = () => {
    commitRename();
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
        <OdooEntryReviewModal
          language={language}
          t={t}
          customDate={customDate}
          setCustomDate={setCustomDate}
          customRef={customRef}
          setCustomRef={setCustomRef}
          journals={journals}
          selectedJournalId={selectedJournalId}
          setSelectedJournalId={setSelectedJournalId}
          previewLines={previewLines}
          accounts={accounts}
          analyticAccounts={analyticAccounts}
          accountDropdownRowIndex={accountDropdownRowIndex}
          setAccountDropdownRowIndex={setAccountDropdownRowIndex}
          partnerDropdownRowIndex={partnerDropdownRowIndex}
          setPartnerDropdownRowIndex={setPartnerDropdownRowIndex}
          analyticDropdownRowIndex={analyticDropdownRowIndex}
          setAnalyticDropdownRowIndex={setAnalyticDropdownRowIndex}
          accountSearchQuery={accountSearchQuery}
          setAccountSearchQuery={setAccountSearchQuery}
          partnerSearchQuery={partnerSearchQuery}
          setPartnerSearchQuery={setPartnerSearchQuery}
          analyticSearchQuery={analyticSearchQuery}
          setAnalyticSearchQuery={setAnalyticSearchQuery}
          totalDebitPrv={totalDebitPrv}
          totalCreditPrv={totalCreditPrv}
          isBalanced={isBalanced}
          isRegistering={isRegistering}
          getPartnerCandidates={getPartnerCandidates}
          handleUpdateLineAccount={handleUpdateLineAccount}
          handleUpdateLinePartner={handleUpdateLinePartner}
          handleUpdateLineAnalytic={handleUpdateLineAnalytic}
          executeOdooRegistration={executeOdooRegistration}
          onClose={() => setShowOdooModal(false)}
        />
      )}

      {showManualInputModal && (
        <ManualEntryModal
          language={language}
          closeLabel={t("team.close")}
          value={manualInputText}
          isParsing={isParsingText}
          onChange={setManualInputText}
          onClose={() => setShowManualInputModal(false)}
          onParse={handleParseManualText}
        />
      )}
    </div>
  );
}
