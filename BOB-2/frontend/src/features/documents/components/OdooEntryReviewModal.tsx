import type { Dispatch, SetStateAction } from "react";

import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import type {
  OdooAccount,
  OdooAnalyticAccount,
  OdooJournal,
  OdooPartner,
  PreviewJournalLine,
} from "@/features/documents/model/types";
import { JournalBalanceSummary } from "./JournalBalanceSummary";
import { JournalEntryMetadata } from "./JournalEntryMetadata";

type Translate = (key: string, replacements?: Record<string, string>) => string;

interface OdooEntryReviewModalProps {
  language: string;
  t: Translate;
  customDate: string;
  setCustomDate: Dispatch<SetStateAction<string>>;
  customRef: string;
  setCustomRef: Dispatch<SetStateAction<string>>;
  journals: OdooJournal[];
  selectedJournalId: number | null;
  setSelectedJournalId: Dispatch<SetStateAction<number | null>>;
  previewLines: PreviewJournalLine[];
  accounts: OdooAccount[];
  analyticAccounts: OdooAnalyticAccount[];
  accountDropdownRowIndex: number | null;
  setAccountDropdownRowIndex: Dispatch<SetStateAction<number | null>>;
  partnerDropdownRowIndex: number | null;
  setPartnerDropdownRowIndex: Dispatch<SetStateAction<number | null>>;
  analyticDropdownRowIndex: number | null;
  setAnalyticDropdownRowIndex: Dispatch<SetStateAction<number | null>>;
  accountSearchQuery: string;
  setAccountSearchQuery: Dispatch<SetStateAction<string>>;
  partnerSearchQuery: string;
  setPartnerSearchQuery: Dispatch<SetStateAction<string>>;
  analyticSearchQuery: string;
  setAnalyticSearchQuery: Dispatch<SetStateAction<string>>;
  totalDebitPrv: number;
  totalCreditPrv: number;
  isBalanced: boolean;
  isRegistering: boolean;
  getPartnerCandidates: (query: string) => OdooPartner[];
  handleUpdateLineAccount: (rowIndex: number, account: OdooAccount) => void;
  handleUpdateLinePartner: (rowIndex: number, partner: OdooPartner | null) => void;
  handleUpdateLineAnalytic: (rowIndex: number, analytic: OdooAnalyticAccount | null) => void;
  executeOdooRegistration: () => void;
  onClose: () => void;
}

export function OdooEntryReviewModal(props: OdooEntryReviewModalProps) {
  const {
    language, t, customDate, setCustomDate, customRef, setCustomRef,
    journals, selectedJournalId, setSelectedJournalId, previewLines,
    accounts, analyticAccounts,
    accountDropdownRowIndex, setAccountDropdownRowIndex,
    partnerDropdownRowIndex, setPartnerDropdownRowIndex,
    analyticDropdownRowIndex, setAnalyticDropdownRowIndex,
    accountSearchQuery, setAccountSearchQuery,
    partnerSearchQuery, setPartnerSearchQuery,
    analyticSearchQuery, setAnalyticSearchQuery,
    totalDebitPrv, totalCreditPrv, isBalanced, isRegistering,
    getPartnerCandidates, handleUpdateLineAccount, handleUpdateLinePartner,
    handleUpdateLineAnalytic, executeOdooRegistration, onClose,
  } = props;

  return (
    <Modal onClose={onClose} panelClassName="wood-panel rounded-[24px] border border-yellow-500/20 shadow-2xl w-full max-w-5xl max-h-[92vh] flex flex-col overflow-hidden">
      {(titleId) => (
        <>
            {/* Header */}
            <div className="flex justify-between items-center px-6 py-4 border-b border-white/10 bg-black/40">
              <div className="flex flex-col">
                <h2 id={titleId} className="text-sm font-bold bg-gradient-to-r from-amber-300 to-yellow-500 bg-clip-text text-transparent">
                  {t("excel.odooJournalTitle")}
                </h2>
                <p className="text-[10px] text-white/50 mt-0.5">
                  {t("excel.odooJournalDesc")}
                </p>
              </div>
              <Button variant="ghost" onClick={() => onClose()}>
                {t("team.close")}
              </Button>
            </div>

            {/* Scrollable Form Body */}
            <div className="flex-1 overflow-auto p-6 flex flex-col gap-5 text-right" dir={language === "ar" ? "rtl" : "ltr"}>
              
              <JournalEntryMetadata language={language} date={customDate} setDate={setCustomDate} reference={customRef} setReference={setCustomRef} journals={journals} selectedJournalId={selectedJournalId} setSelectedJournalId={setSelectedJournalId} />
              <JournalBalanceSummary language={language} totalDebit={totalDebitPrv} totalCredit={totalCreditPrv} isBalanced={isBalanced} />

              {/* Journal Lines Table */}
              <div className="flex flex-col gap-2">
                <span className="text-[10.5px] text-white/60 font-semibold">{language === "ar" ? "قيود الحسابات المقترحة:" : "Proposed Journal Items:"}</span>
                
                <div className="border border-white/10 rounded-xl overflow-x-auto bg-black/20 text-[11px]">
                  <table className="w-full min-w-max text-right border-collapse">
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
              <Button variant="secondary" onClick={() => onClose()}>
                {language === "ar" ? "إلغاء" : "Cancel"}
              </Button>
              <Button
                variant="primary"
                onClick={executeOdooRegistration}
                disabled={isRegistering || !isBalanced || previewLines.some((l) => l.account_id === 0)}
                className="flex items-center gap-1.5"
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
              </Button>
            </div>
        </>
      )}
    </Modal>
  );
}
