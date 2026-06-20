"use client";

import Link from "next/link";
import { useLanguage } from "@/lib/LanguageContext";

export function MainNavigation() {
  const { t } = useLanguage();

  const navItems = [
    { href: "/team", label: t("sidebar.home") },
    { href: "/documents", label: t("sidebar.documents") },
    { href: "/audit", label: t("sidebar.audit") },
    { href: "/erp", label: t("sidebar.erp") },
  ];

  return (
    <aside className="min-h-screen w-80 border-r border-l border-white/10 bg-black/40 p-6 transition-all duration-300">
      <div className="mb-10">
        <h1 className="text-2xl font-bold text-white">
          {t("sidebar.title")}
        </h1>

        <p className="mt-3 text-sm text-gray-400">
          {t("sidebar.subtitle")}
        </p>
      </div>

      <nav className="space-y-3">
        {navItems.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="block rounded-lg border border-gray-700 p-3 text-white hover:bg-gray-800 transition-colors"
          >
            {item.label}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
