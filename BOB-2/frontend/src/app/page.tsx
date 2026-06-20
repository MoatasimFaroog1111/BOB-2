"use client";

import { useLanguage } from "@/lib/LanguageContext";

export default function HomePage() {
  const { language, toggleLanguage, t } = useLanguage();

  return (
    <div className="wood-shell fade-in p-8 h-screen overflow-hidden flex flex-col justify-start items-center">
      <div className="flex flex-col items-center mt-20">
        {/* Circular glowing gold toggle button, engraved look */}
        <button
          onClick={toggleLanguage}
          className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition-all duration-300 cursor-pointer
                     bg-gradient-to-br from-[#221205] to-[#0f0701] border border-[#d9a441]/80 text-[#d9a441]
                     shadow-[inset_0_2px_4px_rgba(0,0,0,0.9),_0_0_12px_rgba(217,164,65,0.75)]
                     hover:shadow-[inset_0_1px_2px_rgba(0,0,0,0.9),_0_0_22px_rgba(217,164,65,0.95)]
                     hover:scale-105 active:scale-95 mb-4"
          title={language === "en" ? "تحويل إلى العربية" : "Switch to English"}
        >
          {language === "en" ? "ع" : "E"}
        </button>

        <p className="gold-text text-sm tracking-[0.4em] uppercase">
          {t("home.subtitle")}
        </p>

        <h1 className="mt-4 text-4xl font-bold text-white">
          {t("home.title")}
        </h1>
      </div>
    </div>
  );
}
