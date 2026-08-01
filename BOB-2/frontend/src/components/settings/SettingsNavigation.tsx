"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { SETTINGS_SECTIONS } from "@/features/settings/sections";
import { useLanguage } from "@/lib/LanguageContext";

export function SettingsNavigation() {
  const pathname = usePathname();
  const { language } = useLanguage();

  return (
    <nav className="flex flex-wrap gap-2" aria-label={language === "ar" ? "أقسام الضبط" : "Settings sections"}>
      {SETTINGS_SECTIONS.map((section) => {
        const active =
          section.href === "/settings"
            ? pathname === section.href
            : pathname === section.href || pathname.startsWith(`${section.href}/`);
        return (
          <Link
            key={section.href}
            href={section.href}
            className={`rounded-xl border px-4 py-2 text-sm font-medium transition ${
              active
                ? "border-amber-500/40 bg-amber-500/15 text-amber-300"
                : "border-white/10 bg-black/20 text-white/60 hover:border-white/20 hover:text-white"
            }`}
          >
            {language === "ar" ? section.titleAr : section.titleEn}
          </Link>
        );
      })}
    </nav>
  );
}
