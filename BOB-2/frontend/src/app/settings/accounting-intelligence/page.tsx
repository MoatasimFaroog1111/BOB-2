import { AccountingDraftReviewWorkflow } from "@/features/settings/accounting-intelligence/AccountingDraftReviewWorkflow";
import { AccountingIntelligencePanel } from "@/features/settings/accounting-intelligence/AccountingIntelligencePanel";

export default function AccountingIntelligenceSettingsPage() {
  return (
    <div className="space-y-6">
      <AccountingDraftReviewWorkflow />
      <AccountingIntelligencePanel />
    </div>
  );
}
