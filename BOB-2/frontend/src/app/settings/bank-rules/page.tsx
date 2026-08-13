import { BankRulesManager } from "@/features/bank-rules/components/BankRulesManager";
import { BankRuleTaxPanel } from "@/features/bank-rules/components/BankRuleTaxPanel";

export default function BankRulesSettingsPage() {
  return (
    <>
      <BankRulesManager />
      <BankRuleTaxPanel />
    </>
  );
}
