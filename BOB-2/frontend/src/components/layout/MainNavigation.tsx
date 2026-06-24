"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLanguage } from "@/lib/LanguageContext";

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


function AccountingAIIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 4h16v16H4z" />
      <path d="M8 8h8" />
      <path d="M8 12h3" />
      <path d="M15 12h1" />
      <path d="M8 16h2" />
      <path d="M14 16h2" />
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

export function MainNavigation() {
  const { t } = useLanguage();
  const pathname = usePathname();

  const navItems = [
    { href: "/team", label: t("sidebar.home"), icon: TeamIcon },
    { href: "/documents", label: t("sidebar.documents"), icon: DocumentIcon },
    { href: "/audit", label: t("sidebar.audit"), icon: AuditIcon },
    { href: "/accounting-ai", label: t("sidebar.accountingAI"), icon: AccountingAIIcon },
    { href: "/erp", label: t("sidebar.erp"), icon: ERPIcon },
  ];

  return (
    <aside className="min-h-screen w-72 border-r border-l border-white/10 bg-black/40 p-5 transition-all duration-300 flex flex-col">
      <div className="mb-8">
        <h1 className="text-xl font-bold text-white">
          {t("sidebar.title")}
        </h1>

        <p className="mt-2 text-xs text-gray-400 leading-relaxed">
          {t("sidebar.subtitle")}
        </p>
      </div>

      <nav className="space-y-1.5 flex-1">
        {navItems.map((item) => {
          const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
          const Icon = item.icon;

          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm font-medium transition-all duration-200 ${
                isActive
                  ? "bg-gradient-to-r from-amber-500/15 to-yellow-600/10 border border-amber-500/30 text-amber-400 shadow-[0_0_12px_rgba(217,164,65,0.15)]"
                  : "border border-transparent text-white/70 hover:bg-white/5 hover:text-white hover:border-white/10"
              }`}
            >
              <Icon className={`w-[18px] h-[18px] flex-shrink-0 ${isActive ? "text-amber-400" : "text-white/40"}`} />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
