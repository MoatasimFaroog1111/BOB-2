import type { ERPProviderId } from "./types";

export type ERPProviderDefinition = {
  id: ERPProviderId;
  label: string;
  urlLabel: string;
  urlPlaceholder: string;
  dbLabel: string;
  dbPlaceholder: string;
  usernameLabel: string;
  usernamePlaceholder: string;
  passwordLabel: string;
  passwordPlaceholder: string;
  requiresDb: boolean;
  requiresUsername: boolean;
  defaultUrl?: string;
  authHint: string;
};

export const ERP_PROVIDERS: ERPProviderDefinition[] = [
  {
    id: "odoo",
    label: "Odoo ERP 16 / 17 / 18 / 19",
    urlLabel: "رابط Odoo",
    urlPlaceholder: "https://your-company.odoo.com",
    dbLabel: "اسم قاعدة البيانات",
    dbPlaceholder: "production_database",
    usernameLabel: "اسم المستخدم أو البريد",
    usernamePlaceholder: "accounting@example.com",
    passwordLabel: "كلمة المرور أو مفتاح API",
    passwordPlaceholder: "أدخل كلمة المرور أو مفتاح API",
    requiresDb: true,
    requiresUsername: true,
    authHint: "يدعم تسجيل Odoo المعتاد أو مفتاح API بحسب إعداد الخادم.",
  },
  {
    id: "sap_s4hana",
    label: "SAP S/4HANA",
    urlLabel: "رابط SAP S/4HANA API",
    urlPlaceholder: "https://my-system-api.s4hana.ondemand.com",
    dbLabel: "معرف النظام / Tenant (اختياري)",
    dbPlaceholder: "PRD",
    usernameLabel: "Communication User",
    usernamePlaceholder: "API_TECHNICAL_USER",
    passwordLabel: "كلمة مرور Communication User",
    passwordPlaceholder: "أدخل كلمة مرور المستخدم التقني",
    requiresDb: false,
    requiresUsername: true,
    authHint: "يتطلب Communication Arrangement يسمح بالوصول إلى Business Partner OData API باستخدام Basic Authentication.",
  },
  {
    id: "oracle_fusion",
    label: "Oracle Fusion Cloud ERP",
    urlLabel: "رابط Oracle Fusion",
    urlPlaceholder: "https://your-instance.fa.region.oraclecloud.com",
    dbLabel: "اسم Tenant (اختياري)",
    dbPlaceholder: "production",
    usernameLabel: "اسم مستخدم Oracle",
    usernamePlaceholder: "integration.user",
    passwordLabel: "كلمة مرور Oracle",
    passwordPlaceholder: "أدخل كلمة مرور مستخدم التكامل",
    requiresDb: false,
    requiresUsername: true,
    authHint: "يختبر الاتصال عبر Financials REST API ويقرأ Ledger واحدًا للتحقق من الصلاحية.",
  },
  {
    id: "business_central",
    label: "Microsoft Dynamics 365 Business Central",
    urlLabel: "Business Central API Prefix",
    urlPlaceholder: "https://api.businesscentral.dynamics.com/v2.0/{tenant}/{environment}",
    dbLabel: "اسم البيئة (اختياري)",
    dbPlaceholder: "Production",
    usernameLabel: "معرف الحساب (اختياري)",
    usernamePlaceholder: "",
    passwordLabel: "OAuth Access Token",
    passwordPlaceholder: "ألصق Access Token صالحًا",
    requiresDb: false,
    requiresUsername: false,
    authHint: "يتطلب Bearer access token صالحًا ويختبر الاتصال عبر API v2.0 /companies.",
  },
  {
    id: "quickbooks_online",
    label: "QuickBooks Online",
    urlLabel: "QuickBooks API URL",
    urlPlaceholder: "https://quickbooks.api.intuit.com",
    dbLabel: "Realm ID / Company ID",
    dbPlaceholder: "1234567890",
    usernameLabel: "الحساب (غير مطلوب)",
    usernamePlaceholder: "",
    passwordLabel: "OAuth Access Token",
    passwordPlaceholder: "ألصق Access Token صالحًا",
    requiresDb: true,
    requiresUsername: false,
    defaultUrl: "https://quickbooks.api.intuit.com",
    authHint: "يتطلب OAuth 2.0 access token وRealm ID الخاص بشركة QuickBooks.",
  },
  {
    id: "xero",
    label: "Xero",
    urlLabel: "Xero API URL",
    urlPlaceholder: "https://api.xero.com",
    dbLabel: "Xero Tenant ID",
    dbPlaceholder: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    usernameLabel: "الحساب (غير مطلوب)",
    usernamePlaceholder: "",
    passwordLabel: "OAuth Access Token",
    passwordPlaceholder: "ألصق Access Token صالحًا",
    requiresDb: true,
    requiresUsername: false,
    defaultUrl: "https://api.xero.com",
    authHint: "يتطلب OAuth 2.0 access token وxero-tenant-id للمؤسسة المتصلة.",
  },
];

export function getERPProviderDefinition(provider: ERPProviderId): ERPProviderDefinition {
  return ERP_PROVIDERS.find((item) => item.id === provider) || ERP_PROVIDERS[0];
}

export function isERPProviderId(value: string): value is ERPProviderId {
  return ERP_PROVIDERS.some((item) => item.id === value);
}
