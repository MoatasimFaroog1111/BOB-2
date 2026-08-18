"use client";

import React, { useMemo, useRef, useState } from "react";

import { SmartAccountantChatView } from "@/features/documents/components/SmartAccountantChatView";
import { SmartAccountantContextView } from "@/features/documents/components/SmartAccountantContextView";
import { SmartAccountantQuickActions } from "@/features/documents/components/SmartAccountantQuickActions";
import {
  buildSmartAccountantCandidateLines,
  buildSmartAccountantProposalSummary,
  mapPreviewLines,
  verifySmartAccountantContext,
} from "@/features/documents/model/smartAccountantWorkspace";
import type {
  OdooAccount,
  OdooAnalyticAccount,
  OdooJournal,
  OdooPartner,
  PreviewJournalLine,
} from "@/features/documents/model/types";

type ChatMessage = { role: "user" | "assistant"; text: string };

type SmartAccountantPanelProps = Readonly<{
  language: string;
  company: { id: number; name: string; currency: string } | null;
  accounts: OdooAccount[];
  partners: OdooPartner[];
  analyticAccounts: OdooAnalyticAccount[];
  journals: OdooJournal[];
  selectedJournalId: number | null;
  previewLines: PreviewJournalLine[];
  gridData: string[][];
  chatMessages: ChatMessage[];
  chatInput: string;
  setChatInput: (value: string) => void;
  chatLoading: boolean;
  isUploading: boolean;
  chatMessagesEndRef: React.RefObject<HTMLDivElement | null>;
  chatFileInputRef: React.RefObject<HTMLInputElement | null>;
  handleSendChatMessage: (event: React.FormEvent) => void;
  handleChatFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
  onManualEntry: () => void;
  onPrepareEntry: () => void;
}>;

export function SmartAccountantPanel({
  language,
  company,
  accounts,
  partners,
  analyticAccounts,
  journals,
  selectedJournalId,
  previewLines,
  gridData,
  chatMessages,
  chatInput,
  setChatInput,
  chatLoading,
  isUploading,
  chatMessagesEndRef,
  chatFileInputRef,
  handleSendChatMessage,
  handleChatFileChange,
  onManualEntry,
  onPrepareEntry,
}: SmartAccountantPanelProps) {
  const ar = language === "ar";
  const inputRef = useRef<HTMLInputElement>(null);
  const [activeView, setActiveView] = useState<"chat" | "context">("chat");

  const selectedJournal = journals.find((journal) => journal.id === selectedJournalId) || null;
  const gridLines = useMemo(() => buildSmartAccountantCandidateLines(gridData), [gridData]);
  const lines = previewLines.length > 0 ? mapPreviewLines(previewLines) : gridLines;
  const verification = useMemo(
    () => verifySmartAccountantContext({
      companySelected: Boolean(company),
      selectedJournal,
      lines,
      accounts,
      partners,
      analyticAccounts,
    }),
    [company, selectedJournal, lines, accounts, partners, analyticAccounts],
  );
  const proposal = useMemo(
    () => buildSmartAccountantProposalSummary({ lines, accounts }),
    [lines, accounts],
  );
  const currency = company?.currency || "SAR";

  const chooseQuickAction = (prompt: string) => {
    setChatInput(prompt);
    setActiveView("chat");
    window.requestAnimationFrame(() => inputRef.current?.focus());
  };

  return (
    <aside
      className="flex h-full w-[22rem] shrink-0 flex-col overflow-hidden rounded-2xl border border-white/10 bg-black/35 text-right shadow-2xl backdrop-blur-md xl:w-[25rem]"
      dir={ar ? "rtl" : "ltr"}
    >
      <header className="border-b border-white/10 px-4 pb-3 pt-4">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-400 shadow-[0_0_9px_rgba(52,211,153,0.9)]" />
              <h2 className="truncate text-sm font-bold text-white">
                {ar ? "المحاسب الذكي" : "Smart Accountant"}
              </h2>
            </div>
            <p className="mt-1 truncate text-[9.5px] text-white/45">
              {company
                ? `${company.name} · ${company.currency}`
                : ar
                  ? "اختر شركة لربط السياق المحاسبي"
                  : "Select a company for accounting context"}
            </p>
          </div>
          <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2 py-1 text-[8px] font-bold text-emerald-300">
            HUMAN REVIEW
          </span>
        </div>

        <div className="mt-3">
          <SmartAccountantQuickActions
            language={language}
            disabled={chatLoading || isUploading}
            onChoosePrompt={chooseQuickAction}
            onAnalyzeDocument={() => chatFileInputRef.current?.click()}
            onManualEntry={onManualEntry}
          />
        </div>
      </header>

      <div className="flex border-b border-white/10 bg-black/20 px-3 pt-2">
        {(["chat", "context"] as const).map((view) => (
          <button
            key={view}
            type="button"
            onClick={() => setActiveView(view)}
            className={`flex-1 border-b-2 px-2 pb-2 text-[10px] font-bold transition ${
              activeView === view
                ? "border-amber-400 text-amber-300"
                : "border-transparent text-white/45 hover:text-white/70"
            }`}
          >
            {view === "chat"
              ? (ar ? "المحادثة" : "Chat")
              : (ar ? "السياق والأدلة" : "Context & Evidence")}
          </button>
        ))}
      </div>

      {activeView === "chat" ? (
        <SmartAccountantChatView
          language={language}
          currency={currency}
          lineCount={lines.length}
          debitTotal={verification.debitTotal}
          creditTotal={verification.creditTotal}
          balanced={verification.balanced}
          proposal={proposal}
          verification={verification}
          chatMessages={chatMessages}
          chatInput={chatInput}
          setChatInput={setChatInput}
          chatLoading={chatLoading}
          isUploading={isUploading}
          chatMessagesEndRef={chatMessagesEndRef}
          chatFileInputRef={chatFileInputRef}
          handleSendChatMessage={handleSendChatMessage}
          handleChatFileChange={handleChatFileChange}
          inputRef={inputRef}
          onEditProposal={onPrepareEntry}
          onApproveProposal={onPrepareEntry}
        />
      ) : (
        <SmartAccountantContextView
          language={language}
          company={company}
          selectedJournal={selectedJournal}
          accountCount={accounts.length}
          partnerCount={partners.length}
          analyticCount={analyticAccounts.length}
          lines={lines}
          verification={verification}
          currency={currency}
          onPrepareEntry={onPrepareEntry}
        />
      )}
    </aside>
  );
}
