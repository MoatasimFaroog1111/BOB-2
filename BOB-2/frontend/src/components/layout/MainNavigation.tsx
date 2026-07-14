"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLanguage } from "@/lib/LanguageContext";

export function MainNavigation() {
  const { t, language } = useLanguage();
  const pathname = usePathname();

  const items = [
    ["/bank-reconciliation", t("bankRecon.pageTitle")],
    ["/documents", t("sidebar.documents")],
    ["/audit", t("sidebar.audit")],
    ["/communication-tools", language === "ar" ? "أدوات الاتصال" : "Communication Tools"],
    ["/erp", t("sidebar.erp")],
    ["/team", t("sidebar.home")],
    ["/settings", language === "ar" ? "الإعدادات" : "Settings"],
    ["/admin/llm", language === "ar" ? "أمان الذكاء الخارجي" : "External AI Security"],
  ];

  return (
    <aside className="min-h-screen w-72 border-r border-l border-white/10 bg-black/40 p-5 flex flex-col">
      <div className="mb-8">
        <h1 className="text-xl font-bold text-white">{t("sidebar.title")}</h1>
        <p className="mt-2 text-xs text-gray-400 leading-relaxed">{t("sidebar.subtitle")}</p>
      </div>
      <nav className="space-y-1.5 flex-1">
        {items.map(([href, label]) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm font-medium transition-all ${active ? "bg-amber-500/15 border border-amber-500/30 text-amber-400" : "border border-transparent text-white/70 hover:bg-white/5 hover:text-white"}`}
            >
              <span className="h-2 w-2 rounded-full bg-current opacity-70" />
              <span>{label}</span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
