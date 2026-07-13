import "./globals.css";
import { Cairo, Outfit } from "next/font/google";

import AuthGate from "@/components/auth/AuthGate";
import JournalEntrySheetActions from "@/components/accounting/JournalEntrySheetActions";
import OdooRegistrationSheetMirror from "@/components/accounting/OdooRegistrationSheetMirror";
import GlobalBackButton from "@/components/layout/GlobalBackButton";
import { MainNavigation } from "@/components/layout/MainNavigation";
import { CompanyProvider } from "@/lib/CompanyContext";
import { LanguageProvider } from "@/lib/LanguageContext";

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
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ar" dir="rtl" className={`${cairo.variable} ${outfit.variable}`}>
      <body className="h-screen overflow-hidden">
        <LanguageProvider>
          <AuthGate>
            <CompanyProvider>
              <main className="guardian-shell flex h-screen w-screen overflow-hidden text-white">
                <MainNavigation />
                <section className="flex-1 h-screen overflow-hidden flex flex-col">
                  <GlobalBackButton />
                  {children}
                </section>
                <JournalEntrySheetActions />
                <OdooRegistrationSheetMirror />
              </main>
            </CompanyProvider>
          </AuthGate>
        </LanguageProvider>
      </body>
    </html>
  );
}
