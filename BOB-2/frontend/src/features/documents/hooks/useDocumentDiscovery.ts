"use client";

import { useEffect, useState } from "react";

import { documentsGateway } from "@/features/documents/api/documentsGateway";
import type {
  OdooAccount,
  OdooAnalyticAccount,
  OdooJournal,
  OdooPartner,
} from "@/features/documents/model/types";

const FALLBACK_JOURNALS: OdooJournal[] = [
  { id: 1, code: "MISC", name: "Miscellaneous Operations", type: "general" },
  { id: 2, code: "BILL", name: "Vendor Bills", type: "purchase" },
  { id: 3, code: "INV", name: "Customer Invoices", type: "sale" },
  { id: 4, code: "BNK1", name: "Bank", type: "bank" },
];

const companyQuery = (companyId: number | null): string =>
  companyId ? `?company_id=${companyId}` : "";

export function useDocumentDiscovery(selectedCompanyId: number | null) {
  const [accounts, setAccounts] = useState<OdooAccount[]>([]);
  const [partners, setPartners] = useState<OdooPartner[]>([]);
  const [analyticAccounts, setAnalyticAccounts] = useState<OdooAnalyticAccount[]>([]);
  const [journals, setJournals] = useState<OdooJournal[]>([]);
  const [selectedJournalId, setSelectedJournalId] = useState<number | null>(null);
  const [journalsLoading, setJournalsLoading] = useState(false);

  useEffect(() => {
    let active = true;
    const load = async () => {
      setJournalsLoading(true);
      const query = companyQuery(selectedCompanyId);
      try {
        const [discovery, partnerResponse, analyticResponse, journalResponse] = await Promise.all([
          documentsGateway.loadDiscovery(),
          documentsGateway.loadPartners(query),
          documentsGateway.loadAnalyticAccounts(query),
          documentsGateway.loadJournals(query),
        ]);
        if (!active) return;

        if (discovery.ok) setAccounts((await discovery.json()).accounts ?? []);
        if (partnerResponse.ok) setPartners(await partnerResponse.json());
        setAnalyticAccounts(analyticResponse.ok ? await analyticResponse.json() : []);

        const loadedJournals: OdooJournal[] = journalResponse.ok
          ? await journalResponse.json()
          : FALLBACK_JOURNALS;
        setJournals(loadedJournals);
        const defaultJournal = loadedJournals.find((journal) => journal.type === "general")
          ?? loadedJournals[0];
        setSelectedJournalId(defaultJournal?.id ?? null);
      } catch (error) {
        if (!active) return;
        console.error("Failed to load ERP discovery data:", error);
        setJournals(FALLBACK_JOURNALS);
        setSelectedJournalId(FALLBACK_JOURNALS[0].id);
      } finally {
        if (active) setJournalsLoading(false);
      }
    };
    void load();
    return () => { active = false; };
  }, [selectedCompanyId]);

  return {
    accounts,
    partners,
    analyticAccounts,
    journals,
    selectedJournalId,
    setSelectedJournalId,
    journalsLoading,
  };
}
