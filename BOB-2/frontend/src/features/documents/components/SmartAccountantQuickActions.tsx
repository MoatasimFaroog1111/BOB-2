"use client";

const actions = [
  {
    icon: "✎",
    ar: "إنشاء قيد",
    en: "Create journal",
    promptAr: "ساعدني في إنشاء قيد محاسبي جديد من البيانات الموجودة، وتحقق من الحسابات والشريك والضريبة قبل أي تنفيذ.",
    promptEn: "Help me create a new journal entry from the available data and validate accounts, partner and tax before any execution.",
  },
  {
    icon: "⌕",
    ar: "بحث في Odoo",
    en: "Search Odoo",
    promptAr: "ابحث في بيانات Odoo الحالية عن الحساب أو الشريك المرتبط بما هو موجود في ورقة العمل واشرح أفضل نتيجة بدون تعديل البيانات.",
    promptEn: "Search current Odoo data for the account or partner related to this worksheet and explain the best result without modifying data.",
  },
  {
    icon: "▣",
    ar: "تحليل حساب",
    en: "Analyze account",
    promptAr: "حلل البيانات المحاسبية الحالية وحدد الحسابات المستخدمة والفروقات أو المخاطر التي تحتاج مراجعة، بدون تنفيذ أي تعديل.",
    promptEn: "Analyze the current accounting data and identify used accounts, variances or risks needing review without making changes.",
  },
  {
    icon: "%",
    ar: "مراجعة ضريبة",
    en: "Review tax",
    promptAr: "راجع المعالجة الضريبية للبيانات الحالية، وحدد ما يحتاج تحققاً بشرياً قبل اعتماد القيد. لا تنفذ أي ترحيل.",
    promptEn: "Review the tax treatment of the current data and identify what requires human verification before approval. Do not post anything.",
  },
] as const;

export function SmartAccountantQuickActions({
  language,
  disabled,
  onChoosePrompt,
  onAnalyzeDocument,
  onManualEntry,
}: Readonly<{
  language: string;
  disabled: boolean;
  onChoosePrompt: (prompt: string) => void;
  onAnalyzeDocument: () => void;
  onManualEntry: () => void;
}>) {
  const ar = language === "ar";

  return (
    <div>
      <div className="grid grid-cols-2 gap-1.5">
        {actions.map((action) => (
          <button
            key={action.en}
            type="button"
            onClick={() => onChoosePrompt(ar ? action.promptAr : action.promptEn)}
            disabled={disabled}
            className="flex min-h-9 items-center gap-2 rounded-lg border border-white/10 bg-white/[0.035] px-2.5 py-2 text-[9.5px] font-semibold text-white/75 transition hover:border-amber-400/30 hover:bg-amber-400/[0.07] hover:text-amber-200 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <span className="text-amber-300">{action.icon}</span>
            <span>{ar ? action.ar : action.en}</span>
          </button>
        ))}
      </div>

      <div className="mt-2 flex gap-1.5">
        <button
          type="button"
          onClick={onAnalyzeDocument}
          disabled={disabled}
          className="flex-1 rounded-lg border border-amber-400/20 bg-amber-400/[0.07] px-2 py-1.5 text-[9.5px] font-bold text-amber-200 hover:bg-amber-400/10 disabled:opacity-40"
        >
          {ar ? "📎 تحليل مستند" : "📎 Analyze document"}
        </button>
        <button
          type="button"
          onClick={onManualEntry}
          className="flex-1 rounded-lg border border-white/10 bg-white/[0.035] px-2 py-1.5 text-[9.5px] font-bold text-white/70 hover:bg-white/[0.06]"
        >
          {ar ? "✎ إدخال يدوي" : "✎ Manual entry"}
        </button>
      </div>
    </div>
  );
}
