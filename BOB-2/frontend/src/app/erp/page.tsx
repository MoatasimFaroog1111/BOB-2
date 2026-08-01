import { redirect } from "next/navigation";

export default function LegacyERPConnectionPage() {
  redirect("/settings/accounting-systems");
}
