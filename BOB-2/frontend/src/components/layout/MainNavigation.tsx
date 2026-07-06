"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLanguage } from "@/lib/LanguageContext";
import { useCompany } from "@/lib/CompanyContext";

function TeamIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}

function DocumentIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </svg>
  );
}

function AuditIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
      <path d="M8 11h6" />
      <path d="M11 8v6" />
    </svg>
  );
}

function BankReconciliationIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="1" y="4" width="22" height="16" rx="2" />
      <line x1="1" y1="10" x2="23" y2="10" />
      <line x1="6" y1="14" x2="10" y2="14" />
      <line x1="6" y1="17" x2="14" y2="17" />
    </svg>
  );
}

function ERPIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
      <line x1="8" y1="21" x2="16" y2="21" />
      <line x1="12" y1="17" x2="12" y2="21" />
    </svg>
  );
}

function SettingsIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

function BuildingIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="4" y="2" width="16" height="20" rx="2" />
      <path d="M9 22v-4h6v4" />
      <path d="M8 6h.01" />
      <path d="M16 6h.01" />
      <path d="M12 6h.01" />
      <path d="M12 10h.01" />
      <path d="M12 14h.01" />
      <path d="M16 10h.01" />
      <path d="M16 14h.01" />
      <path d="M8 10h.01" />
      <path d="M8 14h.01" />
    </svg>
  );
}

export function MainNavigation() {
  const { t, language } = useLanguage();
  const pathname = usePathname();
  const { companies, selectedCompanyId, setSelectedCompanyId } = useCompany();

  const navItems = [
    { href: "/bank-reconciliation", label: t("bankRecon.pageTitle"), icon: BankReconciliationIcon },
    { href: "/documents", label: t("sidebar.documents"), icon: DocumentIcon },
    { href: "/audit", label: t("sidebar.audit"), icon: AuditIcon },
    { href: "/erp", label: t("sidebar.erp"), icon: ERPIcon },
    { href: "/team", label: t("sidebar.home"), icon: TeamIcon },
    { href: "/settings", label: language === "ar" ? "الإعدادات" : "Settings", icon: SettingsIcon },
  ];

  return (
    <aside className="min-h-screen w-72 border-r border-l border-white/10 bg-black/40 p-5 transition-all duration-300 flex flex-col">
      <div className="mb-8">
        <h1 className="text-xl font-bold text-white">{t("sidebar.title")}</h1>
        <p className="mt-2 text-xs text-gray-400 leading-relaxed">{t("sidebar.subtitle")}</p>
      </div>

      {companies.length > 0 && (
        <div className="mb-4">
          <div className="flex items-center gap-2 mb-2">
            <BuildingIcon className="w-4 h-4 text-amber-400/70 flex-shrink-0" />
            <span className="text-[11px] font-semibold text-amber-400/70 uppercase tracking-wider">{t("sidebar.company")}</span>
          </div>
          <select
            value={selectedCompanyId ?? ""}
            onChange={(e) => {
              const val = e.target.value;
              setSelectedCompanyId(val ? parseInt(val, 10) : null);
            }}
            className="w-full bg-black/50 border border-amber-500/25 text-white text-xs rounded-xl px-3 py-2.5 outline-none focus:border-amber-400/60 focus:shadow-[0_0_8px_rgba(217,164,65,0.2)] transition-all duration-200 appearance-none cursor-pointer"
          >
            {companies.map((c) => (
              <option key={c.id} value={c.id}>{c.name}{c.currency ? ` (${c.currency})` : ""}</option>
            ))}
          </select>
        </div>
      )}

      <nav className="space-y-1.5 flex-1">
        {navItems.map((item) => {
          const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
          const Icon = item.icon;
          return (
            <Link key={item.href} href={item.href} className={`flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm font-medium transition-all duration-200 ${isActive ? "bg-gradient-to-r from-amber-500/15 to-yellow-600/10 border border-amber-500/30 text-amber-400 shadow-[0_0_12px_rgba(217,164,65,0.15)]" : "border border-transparent text-white/70 hover:bg-white/5 hover:text-white hover:border-white/10"}`}>
              <Icon className={`w-[18px] h-[18px] flex-shrink-0 ${isActive ? "text-amber-400" : "text-white/40"}`} />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
