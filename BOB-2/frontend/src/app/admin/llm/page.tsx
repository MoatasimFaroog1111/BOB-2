import { redirect } from "next/navigation";

export default function LegacyExternalAIPage() {
  redirect("/settings/ai");
}
