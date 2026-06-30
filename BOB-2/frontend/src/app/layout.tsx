import "./globals.css";
import { MainNavigation } from "@/components/layout/MainNavigation";
import GlobalBackButton from "@/components/layout/GlobalBackButton";
import { LanguageProvider } from "@/lib/LanguageContext";
import { CompanyProvider } from "@/lib/CompanyContext";
import { Cairo, Outfit } from "next/font/google";

const cairo = Cairo({
  subsets: ["arabic"],
  weight: ["300", "400", "600", "700", "800"],
  variable: "--font-cairo",
});

const outfit = Outfit({
  subsets: ["latin"],
  weight: ["300", "400", "600", "700", "800"],
  variable: "--font-outfit",
});

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <LanguageProvider>
      <CompanyProvider>
        <html lang="ar" dir="rtl" className={`${cairo.variable} ${outfit.variable}`}>
          <body className="h-screen overflow-hidden">
            <main className="guardian-shell flex h-screen w-screen overflow-hidden text-white">
              <MainNavigation />
              <section className="flex-1 h-screen overflow-hidden flex flex-col">
                <GlobalBackButton />
                {children}
              </section>
            </main>
          </body>
        </html>
      </CompanyProvider>
    </LanguageProvider>
  );
}
