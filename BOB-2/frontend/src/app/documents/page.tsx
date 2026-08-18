"use client";

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { useLanguage } from "@/lib/LanguageContext";
import { useCompany } from "@/lib/CompanyContext";
import { documentsGateway } from "@/features/documents/api/documentsGateway";
import { useDocumentDiscovery } from "@/features/documents/hooks/useDocumentDiscovery";
import { useSmartAccountingInlineEdit } from "@/features/documents/hooks/useSmartAccountingInlineEdit";
import { useSpreadsheetChat } from "@/features/documents/hooks/useSpreadsheetChat";
import { useSpreadsheetGridInteraction } from "@/features/documents/hooks/useSpreadsheetGridInteraction";
import {
  createEmptyGrid,
  DEFAULT_WORKSHEET_COLUMNS,
  DEFAULT_WORKSHEET_ROWS,
  useWorksheets,
} from "@/features/documents/hooks/useWorksheets";
import { ManualEntryModal } from "@/features/documents/components/ManualEntryModal";
import { OdooEntryReviewModal } from "@/features/documents/components/OdooEntryReviewModal";
import { SmartAccountantPanel } from "@/features/documents/components/SmartAccountantPanel";
import { SpreadsheetGrid } from "@/features/documents/components/SpreadsheetGrid";
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
  const { selectedCompanyId, selectedCompany } = useCompany();
  
  const {
    sheets, setSheets, activeSheet, activeSheetId, setActiveSheetId,
    renameSheetId, renameValue, setRenameValue,
    addRow, deleteRow, addColumn, deleteColumn, clearActiveSheet,
    addSheet, deleteSheet, startRenaming, commitRename,
  } = useWorksheets(language);
  const { gridData, rowCount, colCount } = activeSheet;

  const gridInteraction = useSpreadsheetGridInteraction({
    language,
    activeSheetId,
    gridData,
    rowCount,
    colCount,
    setSheets,
  });
  const { selectionRange } = gridInteraction;

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

  const containerRef = useRef<HTMLDivElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);

  const {
    isUploading,
    chatMessages,
    chatInput,
    setChatInput,
    chatLoading,
    chatMessagesEndRef,
    chatFileInputRef,
    handleSendChatMessage,
    handleChatFileChange,
  } = useSpreadsheetChat({
    language,
    sheets,
    setSheets,
    activeSheetId,
    setActiveSheetId,
    journals,
    selectedJournalId,
  });

  const handleInlineAccountingEdit = useSmartAccountingInlineEdit({
    activeSheetId,
    previewLines,
    setPreviewLines,
    setSheets,
    accounts,
    partners,
    analyticAccounts,
  });

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

  // Focus rename input on open
  useEffect(() => {
    if (renameSheetId && renameInputRef.current) {
      renameInputRef.current.focus();
      renameInputRef.current.select();
    }
  }, [renameSheetId]);

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
      gridInteraction.clearSelection();
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

  const totalDebitPrv = previewLines.reduce((sum, item) => sum + item.debit, 0);
  const totalCreditPrv = previewLines.reduce((sum, item) => sum + item.credit, 0);
  const isBalanced = Math.abs(totalDebitPrv - totalCreditPrv) <= 0.01;

  return (
    <div
      ref={containerRef}
      className="wood-shell fade-in p-6 h-screen overflow-hidden flex flex-row gap-6 justify-start"
      onPaste={gridInteraction.handlePaste}
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

        <SpreadsheetGrid
          language={language}
          gridData={gridData}
          rowCount={rowCount}
          colCount={colCount}
          interaction={gridInteraction}
        />

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

      <SmartAccountantPanel
        language={language}
        company={selectedCompany}
        accounts={accounts}
        partners={partners}
        analyticAccounts={analyticAccounts}
        journals={journals}
        selectedJournalId={selectedJournalId}
        previewLines={previewLines}
        gridData={gridData}
        chatMessages={chatMessages}
        chatInput={chatInput}
        setChatInput={setChatInput}
        chatLoading={chatLoading}
        isUploading={isUploading}
        chatMessagesEndRef={chatMessagesEndRef}
        chatFileInputRef={chatFileInputRef}
        handleSendChatMessage={handleSendChatMessage}
        handleChatFileChange={handleChatFileChange}
        onInlineEdit={handleInlineAccountingEdit}
        onManualEntry={() => {
          setManualInputText("");
          setShowManualInputModal(true);
        }}
        onPrepareEntry={handlePrepareOdooSubmission}
      />

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
