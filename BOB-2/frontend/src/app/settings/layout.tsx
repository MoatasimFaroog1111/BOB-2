import type { ReactNode } from "react";

import { SettingsNavigation } from "@/components/settings/SettingsNavigation";

export default function SettingsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex-1 overflow-y-auto">
      <div className="sticky top-0 z-20 border-b border-white/10 bg-black/70 px-6 py-4 backdrop-blur-xl">
        <SettingsNavigation />
      </div>
      {children}
    </div>
  );
}
