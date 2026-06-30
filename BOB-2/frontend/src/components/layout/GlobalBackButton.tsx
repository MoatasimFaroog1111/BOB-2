"use client";

import { usePathname, useRouter } from "next/navigation";
import { useLanguage } from "@/lib/LanguageContext";

function parentPath(pathname: string) {
  const clean = pathname.split("?")[0].replace(/\/$/, "");
  if (!clean || clean === "") return "/";
  const parts = clean.split("/").filter(Boolean);
  if (parts.length <= 1) return "/";
  return `/${parts.slice(0, -1).join("/")}`;
}

export default function GlobalBackButton() {
  const router = useRouter();
  const pathname = usePathname() || "/";
  const { language } = useLanguage();
  const isAr = language === "ar";

  if (pathname === "/") return null;

  const goBack = () => {
    if (typeof window !== "undefined" && window.history.length > 1) {
      router.back();
      return;
    }
    router.push(parentPath(pathname));
  };

  return (
    <button
      type="button"
      onClick={goBack}
      title={isAr ? "رجوع للخلف صفحة واحدة" : "Go back one page"}
      className="fixed top-3 end-3 z-[9000] rounded-full border border-amber-500/40 bg-black/70 px-3 py-2 text-xs font-bold text-amber-300 shadow-lg shadow-black/30 backdrop-blur-md transition-all hover:-translate-y-0.5 hover:bg-amber-500/15 hover:text-amber-200"
    >
      <span className="inline-flex items-center gap-1">
        <span>{isAr ? "↩" : "←"}</span>
        <span>{isAr ? "رجوع" : "Back"}</span>
      </span>
    </button>
  );
}
