"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { API_BASE_URL } from "./api";

interface Company {
  id: number;
  name: string;
  currency: string;
}

interface CompanyContextProps {
  companies: Company[];
  selectedCompanyId: number | null;
  selectedCompany: Company | null;
  setSelectedCompanyId: (id: number | null) => void;
  loading: boolean;
  refreshCompanies: () => Promise<void>;
}

const CompanyContext = createContext<CompanyContextProps | undefined>(undefined);

function getInitialCompanyId(): number | null {
  if (typeof window === "undefined") return null;
  const saved = localStorage.getItem("selectedCompanyId");
  const parsed = saved ? Number.parseInt(saved, 10) : NaN;
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

export function CompanyProvider({ children }: { children: React.ReactNode }) {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [selectedCompanyId, setSelectedCompanyIdState] = useState<number | null>(getInitialCompanyId);
  const [loading, setLoading] = useState(false);

  const fetchCompanies = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/erp/companies`);
      if (res.ok) {
        const data: Company[] = await res.json();
        setCompanies(data);
        setSelectedCompanyIdState((previous) => {
          if (previous !== null && data.some((company) => company.id === previous)) {
            return previous;
          }
          const saved = getInitialCompanyId();
          if (saved !== null && data.some((company) => company.id === saved)) {
            return saved;
          }
          return data.length > 0 ? data[0].id : null;
        });
      }
    } catch {
      // Silently fail when no ERP connection is available yet.
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchCompanies();
  }, [fetchCompanies]);

  useEffect(() => {
    if (selectedCompanyId !== null) {
      localStorage.setItem("selectedCompanyId", String(selectedCompanyId));
    } else {
      localStorage.removeItem("selectedCompanyId");
    }
  }, [selectedCompanyId]);

  const setSelectedCompanyId = (id: number | null) => {
    setSelectedCompanyIdState(id);
  };

  const selectedCompany = companies.find((company) => company.id === selectedCompanyId) || null;

  return (
    <CompanyContext.Provider
      value={{
        companies,
        selectedCompanyId,
        selectedCompany,
        setSelectedCompanyId,
        loading,
        refreshCompanies: fetchCompanies,
      }}
    >
      {children}
    </CompanyContext.Provider>
  );
}

export function useCompany() {
  const context = useContext(CompanyContext);
  if (!context) {
    throw new Error("useCompany must be used within a CompanyProvider");
  }
  return context;
}
