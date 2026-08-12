export type SettingsSection = {
  href: string;
  titleAr: string;
  titleEn: string;
  descriptionAr: string;
  descriptionEn: string;
  badge: string;
};

export const SETTINGS_SECTIONS: readonly SettingsSection[] = [
  {
    href: "/settings",
    titleAr: "نظرة عامة",
    titleEn: "Overview",
    descriptionAr: "إدارة اللغة والوصول السريع إلى إعدادات التكامل.",
    descriptionEn: "Manage language and access integration settings.",
    badge: "GENERAL",
  },
  {
    href: "/settings/ai",
    titleAr: "نموذج الذكاء الاصطناعي",
    titleEn: "AI Model",
    descriptionAr: "المزود والنموذج ومفتاح API وسياسة الإفصاح.",
    descriptionEn: "Provider, model, API key, and disclosure policy.",
    badge: "AI",
  },
  {
    href: "/settings/accounting-systems",
    titleAr: "الأنظمة المحاسبية",
    titleEn: "Accounting Systems",
    descriptionAr: "اتصال Odoo وبيانات الاعتماد واختبارات الاتصال.",
    descriptionEn: "Odoo connection, credentials, and connection tests.",
    badge: "ERP",
  },
  {
    href: "/settings/bank-rules",
    titleAr: "قواعد البنك",
    titleEn: "Bank Rules",
    descriptionAr: "إنشاء واختبار ومراجعة واعتماد قواعد تصنيف الحركات البنكية داخل BOB مع مراجع الحسابات من Odoo.",
    descriptionEn: "Create, test, review, and approve BOB-owned bank classification rules using Odoo accounting references.",
    badge: "BANK RULES",
  },
] as const;
