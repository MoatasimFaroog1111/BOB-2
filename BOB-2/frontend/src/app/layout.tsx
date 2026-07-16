import "./globals.css";
import { connection } from "next/server";

import AuthGate from "@/components/auth/AuthGate";
import JournalEntrySheetActions from "@/components/accounting/JournalEntrySheetActions";
import OdooRegistrationSheetMirror from "@/components/accounting/OdooRegistrationSheetMirror";
import GlobalBackButton from "@/components/layout/GlobalBackButton";
import { MainNavigation } from "@/components/layout/MainNavigation";
import { CompanyProvider } from "@/lib/CompanyContext";
import { LanguageProvider } from "@/lib/LanguageContext";

const localFontVariables = {
  "--font-cairo": "Tahoma, Arial, sans-serif",
  "--font-outfit": '"Segoe UI", Arial, sans-serif',
} as React.CSSProperties;

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // A fresh CSP nonce is generated for every request by src/proxy.ts. Dynamic
  // rendering ensures Next.js can apply that nonce to framework scripts and styles.
  await connection();

  return (
    <html lang="ar" dir="rtl" style={localFontVariables}>
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