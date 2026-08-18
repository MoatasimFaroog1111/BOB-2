"use client";

import React, { useEffect, useRef, useState } from "react";

import { useLanguage } from "@/lib/LanguageContext";
import { useCompany } from "@/lib/CompanyContext";
import { documentsGateway } from "@/features/documents/api/documentsGateway";
import { ManualEntryModal } from "@/features/documents/components/ManualEntryModal";
import { OdooEntryReviewModal } from "@/features/documents/components/OdooEntryReviewModal";
import {
  SmartAccountantCockpitBar,
  type SmartAccountantWorkspaceMode,
} from "@/features/documents/components/SmartAccountantCockpitBar";
import { SmartAccountantPanel } from "@/features/documents/components/SmartAccountantPanel";
import { SpreadsheetGrid } from "@/features/documents/components/SpreadsheetGrid";
import { SpreadsheetWorkspaceControls } from "@/features/documents/components/SpreadsheetWorkspaceControls";
import { WorksheetTabStrip } from "@/features/documents/components/WorksheetTabStrip";
import { useDocumentDiscovery } from "@/features/documents/hooks/useDocumentDiscovery";
import { useSmartAccountingInlineEdit } from "@/features/documents/hooks/useSmartAccountingInlineEdit";
import { useSpreadsheetChat } from "@/features/documents/hooks/useSpreadsheetChat";
import { useSpreadsheetGridInteraction } from "@/features/documents/hooks/useSpreadsheetGridInteraction";
import { useWorksheets } from "@/features/documents/hooks/useWorksheets";
import {
  normalizeLookupValue,
  normalizePartnerName,
  partnerSimilarityScore,
} from "@/features/documents/model/partnerMatching";
import { prepareJournalEntry } from "@/features/documents/model/prepareJournalEntry";
import type {
  OdooAccount,
  OdooAnalyticAccount,
  OdooPartner,
  PreviewJournalLine,
} from "@/features/documents/model/types";

export default function DocumentIntelligencePage() {
  const { t, language } = useLanguage();
  const { selectedCompanyId, selectedCompany } = useCompany();
  const [workspaceMode, setWorkspaceMode] = useState<SmartAccountantWorkspaceMode>("assistant");

  const {
    sheets,
    setSheets,
    activeSheet,
    activeSheetId,
    setActiveSheetId,
    renameSheetId,
    renameValue,
    setRenameValue,
    addRow,
    deleteRow,
    addColumn,
    deleteColumn,
    clearActiveSheet,
    addSheet,
    deleteSheet,
    startRenaming,
    commitRename,
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

  const handleParseManualText = async () => {
    if (!manualInputText.trim() || isParsingText) return;
    setIsParsingText(true);
    try {
      const res = await documentsGateway.parseManualText({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: manualInputText }),
      });

      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      if (data.status === "error") throw new Error(data.message);

      if (data.lines && data.lines.length > 0) {
        setPreviewLines(
          data.lines.map((line: PreviewJournalLine) => ({
            ...line,
            analytic_account_id: line.analytic_account_id ?? null,
            analytic_account_name: line.analytic_account_name || "",
          })),
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
            : "No journal entry lines could be parsed from the text. Please ensure the format is correct.",
        );
      }
    } catch (err: unknown) {
      console.error(err);
      const message = err instanceof Error ? err.message : String(err);
      alert((language === "ar" ? "فشل تحليل النص: " : "Failed to parse text: ") + message);
    } finally {
      setIsParsingText(false);
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
      if (!partner?.name) continue;
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
      .map((partner) => ({ partner, score: partnerSimilarityScore(query, partner.name || "") }))
      .filter((item) => item.score >= 0.35)
      .sort((a, b) => b.score - a.score)
      .map((item) => item.partner);
  };

  useEffect(() => {
    if (renameSheetId && renameInputRef.current) {
      renameInputRef.current.focus();
      renameInputRef.current.select();
    }
  }, [renameSheetId]);

  const handleClearSheet = () => {
    if (
      confirm(
        language === "ar"
          ? "هل أنت متأكد من مسح جميع بيانات ورقة العمل الحالية؟"
          : "Are you sure you want to clear the active sheet data?",
      )
    ) {
      clearActiveSheet();
      gridInteraction.clearSelection();
    }
  };

  const handleExportCSV = () => {
    const csvRows: string[] = [];
    for (let rowIndex = 0; rowIndex < rowCount; rowIndex += 1) {
      const row = gridData[rowIndex].map((value) => `"${value.replace(/"/g, '""')}"`);
      csvRows.push(row.join(","));
    }
    const blob = new Blob(["\ufeff" + csvRows.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${activeSheet.name}_export_${new Date().toISOString().slice(0, 10)}.csv`;
    link.style.visibility = "hidden";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

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
          : "Please select/enter at least 2 journal lines to register.",
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
    setPreviewLines((previous) => previous.map((line, index) => index === rowIndex
      ? {
          ...line,
          account_id: account.id,
          account_name: `${account.code} ${account.name}`,
          account_code: account.code,
        }
      : line));
    setAccountDropdownRowIndex(null);
  };

  const handleUpdateLinePartner = (rowIndex: number, partner: OdooPartner | null) => {
    setPreviewLines((previous) => previous.map((line, index) => index === rowIndex
      ? {
          ...line,
          partner_id: partner?.id ?? null,
          partner_name: partner?.name ?? "",
        }
      : line));
    setPartnerDropdownRowIndex(null);
  };

  const handleUpdateLineAnalytic = (rowIndex: number, analytic: OdooAnalyticAccount | null) => {
    setPreviewLines((previous) => previous.map((line, index) => index === rowIndex
      ? {
          ...line,
          analytic_account_id: analytic?.id ?? null,
          analytic_account_name: analytic?.name ?? "",
        }
      : line));
    setAnalyticDropdownRowIndex(null);
  };

  const executeOdooRegistration = async () => {
    const totalDebit = previewLines.reduce((sum, line) => sum + line.debit, 0);
    const totalCredit = previewLines.reduce((sum, line) => sum + line.credit, 0);

    if (Math.abs(totalDebit - totalCredit) > 0.01) {
      alert(t("excel.unbalanced") || "Unbalanced entry! Debit and Credit totals must match.");
      return;
    }

    if (previewLines.some((line) => line.account_id === 0)) {
      alert(
        language === "ar"
          ? "يرجى تحديد حساب محاسبي معرف لجميع القيود قبل المتابعة."
          : "Please resolve/select valid Odoo accounts for all lines before submitting.",
      );
      return;
    }

    setIsRegistering(true);
    try {
      const selectedJournal = journals.find((journal) => journal.id === selectedJournalId);
      const payload = {
        filename: `spreadsheet_entry_${new Date().toISOString().slice(0, 10)}.pdf`,
        document_class: customJournal || selectedJournal?.type || "general_journal",
        journal_id: selectedJournalId,
        amount: totalDebit,
        date: customDate || new Date().toISOString().slice(0, 10),
        partner_name: previewLines[0]?.partner_name || "",
        partner_id: previewLines[0]?.partner_id || null,
        ref: customRef || `Manual Excel Entry ${new Date().toLocaleDateString()}`,
        raw_text: JSON.stringify(previewLines),
        lines: previewLines.map((line) => ({
          account_id: line.account_id,
          account_code: line.account_code,
          account_name: line.account_name,
          debit: line.debit,
          credit: line.credit,
          name: line.name,
          partner_id: line.partner_id,
          analytic_account_id: line.analytic_account_id,
          analytic_account_name: line.analytic_account_name,
        })),
      };

      const res = await documentsGateway.registerDocument({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());

      alert(t("excel.successPost") || "Successfully registered in Odoo!");
      setShowOdooModal(false);
    } catch (err: unknown) {
      console.error(err);
      const message = err instanceof Error ? err.message : String(err);
      alert(`${t("excel.errorPost") || "Failed to register:"} ${message}`);
    } finally {
      setIsRegistering(false);
    }
  };

  const handleDeleteSheet = (id: string, event: React.MouseEvent) => {
    event.stopPropagation();
    if (sheets.length <= 1) return;
    if (
      confirm(
        language === "ar"
          ? "هل أنت متأكد من حذف ورقة العمل هذه بالكامل؟ لا يمكن التراجع عن هذا الإجراء."
          : "Are you sure you want to delete this worksheet? This action cannot be undone.",
      )
    ) {
      deleteSheet(id);
    }
  };

  const totalDebitPrv = previewLines.reduce((sum, item) => sum + item.debit, 0);
  const totalCreditPrv = previewLines.reduce((sum, item) => sum + item.credit, 0);
  const isBalanced = Math.abs(totalDebitPrv - totalCreditPrv) <= 0.01;

  const openManualEntry = () => {
    setManualInputText("");
    setShowManualInputModal(true);
  };

  return (
    <div
      ref={containerRef}
      className="wood-shell fade-in flex h-full min-h-0 flex-col gap-3 overflow-hidden p-3 md:p-4"
      onPaste={gridInteraction.handlePaste}
    >
      <SmartAccountantCockpitBar
        language={language}
        mode={workspaceMode}
        onModeChange={setWorkspaceMode}
        companyName={selectedCompany?.name}
        currency={selectedCompany?.currency}
        journals={journals}
        selectedJournalId={selectedJournalId}
        onJournalChange={setSelectedJournalId}
        journalsLoading={journalsLoading}
        onManualEntry={openManualEntry}
        onReview={handlePrepareOdooSubmission}
      />

      <main className="min-h-0 flex-1 overflow-hidden">
        {workspaceMode === "assistant" ? (
          <div className="mx-auto h-full w-full max-w-[72rem]">
            <SmartAccountantPanel
              variant="focus"
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
              onManualEntry={openManualEntry}
              onPrepareEntry={handlePrepareOdooSubmission}
            />
          </div>
        ) : (
          <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border border-white/10 bg-black/30 shadow-2xl backdrop-blur-md">
            <SpreadsheetWorkspaceControls
              language={language}
              onAddRow={addRow}
              onDeleteRow={deleteRow}
              onAddColumn={addColumn}
              onDeleteColumn={deleteColumn}
              onClear={handleClearSheet}
              onExport={handleExportCSV}
            />
            <div className="min-h-0 flex-1 overflow-hidden p-2">
              <SpreadsheetGrid
                language={language}
                gridData={gridData}
                rowCount={rowCount}
                colCount={colCount}
                interaction={gridInteraction}
              />
            </div>
            <WorksheetTabStrip
              language={language}
              sheets={sheets}
              activeSheetId={activeSheetId}
              renameSheetId={renameSheetId}
              renameValue={renameValue}
              renameInputRef={renameInputRef}
              onRenameValueChange={setRenameValue}
              onActivate={setActiveSheetId}
              onStartRename={startRenaming}
              onCommitRename={commitRename}
              onDelete={handleDeleteSheet}
              onAdd={addSheet}
            />
          </section>
        )}
      </main>

      {showOdooModal ? (
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
      ) : null}

      {showManualInputModal ? (
        <ManualEntryModal
          language={language}
          closeLabel={t("team.close")}
          value={manualInputText}
          isParsing={isParsingText}
          onChange={setManualInputText}
          onClose={() => setShowManualInputModal(false)}
          onParse={handleParseManualText}
        />
      ) : null}
    </div>
  );
}
