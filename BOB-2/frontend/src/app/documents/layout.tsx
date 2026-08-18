import type { ReactNode } from "react";

import { SmartAccountantWorkspaceFrame } from "@/features/documents/components/SmartAccountantWorkspaceFrame";

export default function DocumentsLayout({ children }: { children: ReactNode }) {
  return <SmartAccountantWorkspaceFrame>{children}</SmartAccountantWorkspaceFrame>;
}
