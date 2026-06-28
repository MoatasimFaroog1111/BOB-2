"use client";

import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
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
  return saved ? parseInt(saved, 10) : null;
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
        setSelectedCompanyIdState((prev) => {
          if (prev !== null && data.some((c) => c.id === prev)) return prev;
          const saved = getInitialCompanyId();
          const valid = saved && data.some((c) => c.id === saved);
          return valid ? saved : data.length > 0 ? data[0].id : null;
        });
      }
    } catch {
      // silently fail — no ERP connection yet
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCompanies();
  }, [fetchCompanies]);

  const setSelectedCompanyId = (id: number | null) => {
    setSelectedCompanyIdState(id);
    if (id !== null) {
      localStorage.setItem("selectedCompanyId", String(id));
    } else {
      localStorage.removeItem("selectedCompanyId");
    }
  };

  const selectedCompany = companies.find((c) => c.id === selectedCompanyId) || null;

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
