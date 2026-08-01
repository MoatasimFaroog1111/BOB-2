import Link from "next/link";

import { ERPConnectionSettingsPanel } from "@/features/settings/erp/ERPConnectionSettingsPanel";

export default function AccountingSystemsSettingsPage() {
  return (
    <div>
      <ERPConnectionSettingsPanel />
      <div className="px-6 pb-6">
        <Link
          href="/erp/discovery"
          className="block rounded-2xl border border-white/10 bg-black/30 p-5 transition hover:border-amber-500/35 hover:bg-amber-500/5"
        >
          <p className="text-xs font-semibold tracking-wider text-amber-400">ERP DISCOVERY</p>
          <h2 className="mt-2 text-lg font-semibold text-white">استكشاف الهيكل المالي في Odoo</h2>
          <p className="mt-2 text-sm leading-6 text-white/50">
            بعد حفظ الاتصال، استكشف الحسابات والدفاتر والضرائب والشركاء ومراكز التكلفة.
          </p>
        </Link>
      </div>
    </div>
  );
}
