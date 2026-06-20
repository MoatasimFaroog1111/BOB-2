"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { API_BASE_URL } from "@/lib/api";
import { useLanguage } from "@/lib/LanguageContext";

export default function ERPConnectionPage() {
  const { t, language } = useLanguage();

  const [url, setUrl] = useState("");
  const [db, setDb] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const [loading, setLoading] = useState(false);
  const [testResult, setTestResult] = useState<any>(null);
  const [savedConnection, setSavedConnection] = useState<any>(null);
  const [companyInfo, setCompanyInfo] = useState<any>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  const [telegramToken, setTelegramToken] = useState("");
  const [telegramActive, setTelegramActive] = useState(false);
  const [telegramBotInfo, setTelegramBotInfo] = useState<any>(null);
  const [telegramLoading, setTelegramLoading] = useState(false);
  const [telegramSuccessMsg, setTelegramSuccessMsg] = useState("");
  const [telegramErrorMsg, setTelegramErrorMsg] = useState("");

  useEffect(() => {
    fetchSavedConnection();
    fetchTelegramConfig();
  }, []);

  const fetchSavedConnection = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/connection`);
      if (response.ok) {
        const data = await response.json();
        if (data) {
          setSavedConnection(data);
          setUrl(data.url || "");
          setDb(data.db || "");
          setUsername(data.username || "");
          fetchCompanyInfo();
        }
      }
    } catch (err) {
      console.error("Failed to fetch saved ERP connection:", err);
    }
  };

  const fetchTelegramConfig = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/telegram-config`);
      if (response.ok) {
        const data = await response.json();
        setTelegramToken(data.token || "");
        setTelegramActive(data.is_active || false);
        setTelegramBotInfo(data.bot_info);
      }
    } catch (err) {
      console.error("Failed to fetch Telegram configuration:", err);
    }
  };

  const handleSaveTelegram = async (e: React.FormEvent) => {
    e.preventDefault();
    setTelegramLoading(true);
    setTelegramErrorMsg("");
    setTelegramSuccessMsg("");

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/telegram-config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: telegramToken, is_active: true }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "فشل تفعيل البوت. يرجى التأكد من التوكن.");
      }

      setTelegramActive(true);
      setTelegramSuccessMsg(language === "ar" ? "تم تفعيل بوت تليجرام بنجاح!" : "Telegram Bot activated successfully!");
      fetchTelegramConfig();
    } catch (err: any) {
      setTelegramErrorMsg(err.message || "فشل التفعيل.");
    } finally {
      setTelegramLoading(false);
    }
  };

  const handleDeactivateTelegram = async () => {
    setTelegramLoading(true);
    setTelegramErrorMsg("");
    setTelegramSuccessMsg("");

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/telegram-config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: telegramToken, is_active: false }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "فشل إيقاف البوت.");
      }

      setTelegramActive(false);
      setTelegramBotInfo(null);
      setTelegramSuccessMsg(language === "ar" ? "تم تعطيل البوت بنجاح." : "Telegram Bot deactivated successfully.");
    } catch (err: any) {
      setTelegramErrorMsg(err.message || "فشل التعطيل.");
    } finally {
      setTelegramLoading(false);
    }
  };

  const fetchCompanyInfo = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/company-info-saved`);
      if (response.ok) {
        const data = await response.json();
        setCompanyInfo(data);
      }
    } catch (err) {
      console.error("Failed to fetch company info:", err);
    }
  };

  const handleTestConnection = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setErrorMsg("");
    setSuccessMsg("");
    setTestResult(null);

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/test-connection`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: "odoo", url, db, username, password }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || t("erp.failConnect"));
      }

      setTestResult(data);
      if (data.connected) {
        setSuccessMsg(
          t("erp.successTest", { version: data.odoo_version?.server_version || "18/19" })
        );
      } else {
        setErrorMsg(t("erp.failConnect"));
      }
    } catch (err: any) {
      setErrorMsg(err.message || t("erp.errorTest"));
    } finally {
      setLoading(false);
    }
  };

  const handleSaveConnection = async () => {
    setLoading(true);
    setErrorMsg("");
    setSuccessMsg("");

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/connection`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: "odoo", url, db, username, password }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || t("erp.errorSave"));
      }

      setSavedConnection(data);
      setSuccessMsg(t("erp.successSave"));
      fetchCompanyInfo();
    } catch (err: any) {
      setErrorMsg(err.message || t("erp.errorSave"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fade-in p-4 w-full h-full flex flex-col justify-start overflow-hidden text-[11px]">
      {/* Header section */}
      <div className="mb-2 flex items-center justify-between">
        <div>
          <Link
            href="/"
            className="gold-text text-[10px] tracking-widest hover:underline uppercase transition-all"
          >
            {t("erp.back")}
          </Link>
          <h1 className="mt-0.5 text-xl font-bold">{t("erp.title")}</h1>
          <p className="text-[11px] text-white/70">
            {t("erp.desc")}
          </p>
        </div>

        {/* Dynamic connection status indicator */}
        <div className="flex items-center gap-2.5 bg-black/30 px-3 py-1.5 rounded-xl border border-white/10 backdrop-blur-sm">
          <div>
            <p className="text-[10px] text-white/50 text-right">{t("erp.status")}</p>
            <p className="font-bold text-xs">
              {savedConnection ? t("erp.connected") : t("erp.disconnected")}
            </p>
          </div>
          <div
            className={`w-6 h-6 rounded-full flex items-center justify-center border ${
              savedConnection
                ? "bg-green-500/20 border-green-400 shadow-[0_0_10px_rgba(74,222,128,0.5)]"
                : "bg-red-500/20 border-red-400"
            }`}
          >
            <div
              className={`w-2 h-2 rounded-full ${
                savedConnection ? "bg-green-400" : "bg-red-400"
              }`}
            />
          </div>
        </div>
      </div>

      <div className="gold-divider mb-4" />

      {/* Main Grid Layout */}
      <div className="flex-1 min-h-0 grid gap-3 lg:grid-cols-12 overflow-hidden mb-2">
        {/* Left Side: Connection Form */}
        <div className="lg:col-span-7 wood-panel !p-3 rounded-[16px] flex flex-col overflow-y-auto min-h-0">
          <form onSubmit={handleTestConnection} className="space-y-3">
            <h2 className="text-lg font-semibold gold-text">{t("erp.setupTitle")}</h2>
            <p className="text-white/60 text-sm">
              {t("erp.setupDesc")}
            </p>

            <div className="space-y-0.5">
              <label className="block text-[11px] font-medium gold-text">{t("erp.provider")}</label>
              <select className="w-full bg-black/40 border border-white/20 text-white px-2 py-1 text-xs rounded-lg outline-none focus:border-yellow-500 transition-colors">
                <option value="odoo">Odoo ERP (v16 / v17 / v18 / v19)</option>
                <option value="sap" disabled>SAP S/4HANA (Coming Soon)</option>
                <option value="oracle" disabled>Oracle NetSuite (Coming Soon)</option>
              </select>
            </div>

            <div className="space-y-0.5">
              <label className="block text-[11px] font-medium gold-text">{t("erp.url")}</label>
              <input
                type="url"
                required
                placeholder="https://company.odoo.com"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                className="w-full bg-black/40 border border-white/20 text-white px-2 py-1 text-xs rounded-lg outline-none focus:border-yellow-500 transition-colors"
              />
            </div>

            <div className="grid gap-2 md:grid-cols-2">
              <div className="space-y-0.5">
                <label className="block text-[11px] font-medium gold-text">{t("erp.db")}</label>
                <input
                  type="text"
                  required
                  placeholder="db_name"
                  value={db}
                  onChange={(e) => setDb(e.target.value)}
                  className="w-full bg-black/40 border border-white/20 text-white px-2 py-1 text-xs rounded-lg outline-none focus:border-yellow-500 transition-colors"
                />
              </div>

              <div className="space-y-0.5">
                <label className="block text-[11px] font-medium gold-text">{t("erp.username")}</label>
                <input
                  type="text"
                  required
                  placeholder="admin@company.com"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full bg-black/40 border border-white/20 text-white px-2 py-1 text-xs rounded-lg outline-none focus:border-yellow-500 transition-colors"
                />
              </div>
            </div>

            <div className="space-y-0.5">
              <label className="block text-[11px] font-medium gold-text">{t("erp.password")}</label>
              <input
                type="password"
                placeholder={savedConnection ? "••••••••••••••••" : t("erp.password")}
                required={!savedConnection}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-black/40 border border-white/20 text-white px-2 py-1 text-xs rounded-lg outline-none focus:border-yellow-500 transition-colors"
              />
            </div>

            {/* Response Alerts */}
            {errorMsg && (
              <div className="bg-red-500/10 border border-red-500/40 p-4 rounded-xl text-red-300 text-sm">
                ❌ {errorMsg}
              </div>
            )}

            {successMsg && (
              <div className="bg-green-500/10 border border-green-500/40 p-4 rounded-xl text-green-300 text-sm">
                ✅ {successMsg}
              </div>
            )}

            {/* Actions Panel */}
            <div className="flex gap-2 pt-2">
              <button
                type="submit"
                disabled={loading}
                className="flex-1 cursor-pointer bg-white/10 hover:bg-white/20 text-white font-medium py-1.5 px-3 rounded-lg border border-white/20 text-xs transition-all active:scale-[0.98] disabled:opacity-50"
              >
                {loading ? t("erp.verifying") : t("erp.testBtn")}
              </button>

              <button
                type="button"
                onClick={handleSaveConnection}
                disabled={loading || (!password && !savedConnection)}
                className="flex-1 cursor-pointer bg-gradient-to-r from-amber-500 to-yellow-600 hover:from-amber-600 hover:to-yellow-700 text-black font-bold py-1.5 px-3 rounded-lg text-xs transition-all shadow-lg active:scale-[0.98] disabled:opacity-50"
              >
                {loading ? t("erp.saving") : t("erp.saveBtn")}
              </button>
            </div>
          </form>
        </div>

        {/* Right Side: Active Connection Meta & Company Info */}
        <div className="lg:col-span-5 flex flex-col gap-2 overflow-y-auto min-h-0">
          {/* Active connection meta info card */}
          <div className="wood-card !p-3">
            <h3 className="text-sm font-bold gold-text mb-2">{t("erp.savedDetails")}</h3>
            {savedConnection ? (
              <div className="space-y-1.5 text-xs">
                <div className="flex justify-between border-b border-white/10 pb-1">
                  <span className="text-white/50">{t("erp.provider")}:</span>
                  <span className="font-semibold uppercase">{savedConnection.provider}</span>
                </div>
                <div className="flex justify-between border-b border-white/10 pb-1">
                  <span className="text-white/50">{t("erp.url")}:</span>
                  <span className="font-semibold truncate max-w-[180px]">{savedConnection.url}</span>
                </div>
                <div className="flex justify-between border-b border-white/10 pb-1">
                  <span className="text-white/50">{t("erp.db")}:</span>
                  <span className="font-semibold">{savedConnection.db}</span>
                </div>
                <div className="flex justify-between border-b border-white/10 pb-1">
                  <span className="text-white/50">{t("erp.username")}:</span>
                  <span className="font-semibold truncate max-w-[180px]">{savedConnection.username}</span>
                </div>
                <div className="pt-2">
                  <Link
                    href="/erp/discovery"
                    className="w-full text-center block bg-gradient-to-r from-amber-500 to-yellow-600 hover:from-amber-600 hover:to-yellow-700 text-black font-bold py-1.5 px-3 rounded-lg transition-all shadow-md text-xs active:scale-[0.98]"
                  >
                    {t("erp.goDiscovery")}
                  </Link>
                </div>
              </div>
            ) : (
              <p className="text-white/50 text-sm">
                {t("erp.noSaved")}
              </p>
            )}
          </div>

          {/* Odoo Instance Data (Discovered) */}
          {companyInfo && (
            <div className="wood-card">
              <h3 className="text-2xl font-bold gold-text mb-4">{t("erp.intelligence")}</h3>
              <div className="space-y-4">
                <div className="bg-black/30 p-4 rounded-xl border border-white/5 flex justify-between items-center">
                  <div>
                    <p className="text-xs text-white/50">{t("erp.totalAccounts")}</p>
                    <p className="text-2xl font-bold gold-text mt-1">{companyInfo.accounts_count}</p>
                  </div>
                  <span className="bg-amber-500/10 text-amber-300 text-xs px-2.5 py-1 rounded-full border border-amber-500/35">
                    {t("erp.discovered")}
                  </span>
                </div>

                <div className="space-y-2 text-sm">
                  <h4 className="font-semibold text-white/80 border-b border-white/10 pb-2">{t("erp.companiesHeader")}</h4>
                  <div className="space-y-2 max-h-[160px] overflow-y-auto pr-1">
                    {companyInfo.companies?.map((company: any, index: number) => (
                      <div key={index} className="bg-black/20 p-2.5 rounded-lg border border-white/5 space-y-0.5">
                        <p className="font-bold text-white text-xs">{company.name}</p>
                        {company.email && <p className="text-[10px] text-white/50">Email: {company.email}</p>}
                        {company.phone && <p className="text-[10px] text-white/50">Phone: {company.phone}</p>}
                        {company.currency_id && (
                          <p className="text-[10px] text-white/60 mt-0.5">
                            {t("erp.currency")}: <span className="gold-text font-semibold">{company.currency_id[1]}</span>
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Telegram Bot Integration Card */}
          <div className="wood-card !p-3">
            <h3 className="text-sm font-bold gold-text mb-2">
              {language === "ar" ? "ربط بوت تليجرام (Telegram Bot)" : "Telegram Bot Integration"}
            </h3>
            
            {telegramActive ? (
              <div className="space-y-2.5 text-xs">
                <div className="flex justify-between items-center bg-black/25 px-2.5 py-1.5 rounded-lg border border-green-500/20">
                  <span className="text-white/50">{language === "ar" ? "حالة البوت:" : "Bot Status:"}</span>
                  <span className="font-semibold text-green-400 flex items-center gap-1">
                    <span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-ping" />
                    {language === "ar" ? "نشط ومفعل" : "Active & Running"}
                  </span>
                </div>
                {telegramBotInfo && (
                  <div className="bg-black/15 p-2 rounded-lg space-y-1 text-[11px] border border-white/5">
                    <div className="flex justify-between">
                      <span className="text-white/50">{language === "ar" ? "اسم البوت:" : "Bot Name:"}</span>
                      <span className="font-semibold text-white">{telegramBotInfo.first_name}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-white/50">{language === "ar" ? "معرّف البوت:" : "Username:"}</span>
                      <a 
                        href={`https://t.me/${telegramBotInfo.username}`} 
                        target="_blank" 
                        rel="noreferrer"
                        className="font-semibold text-amber-400 hover:underline"
                      >
                        @{telegramBotInfo.username}
                      </a>
                    </div>
                  </div>
                )}
                
                <div className="text-[10px] text-white/60 space-y-1 bg-black/10 p-2 rounded-lg border border-white/5 leading-relaxed">
                  <p className="font-bold gold-text mb-0.5">{language === "ar" ? "💡 كيف تستخدم البوت؟" : "💡 How to use?"}</p>
                  <p>{language === "ar" ? "• افتح المحادثة مع البوت في تليجرام." : "• Open the chat with the bot in Telegram."}</p>
                  <p>{language === "ar" ? "• أرسل فواتيرك أو إيصالاتك (PDF أو صور)." : "• Send invoices or receipts (PDF or images)."}</p>
                  <p>{language === "ar" ? "• راجع قيد اليومية المقترح وقم بالترحيل بضغطة زر!" : "• Review the proposed entry and post with a single click!"}</p>
                </div>
                
                <button
                  type="button"
                  onClick={handleDeactivateTelegram}
                  disabled={telegramLoading}
                  className="w-full cursor-pointer bg-red-950/20 hover:bg-red-900/30 text-red-400 border border-red-500/30 font-medium py-1 rounded-lg text-xs transition-all active:scale-[0.98] disabled:opacity-50"
                >
                  {telegramLoading ? (language === "ar" ? "جاري التعطيل..." : "Deactivating...") : (language === "ar" ? "تعطيل وإيقاف البوت" : "Deactivate Bot")}
                </button>
              </div>
            ) : (
              <form onSubmit={handleSaveTelegram} className="space-y-2">
                <p className="text-white/60 text-[11px] leading-relaxed">
                  {language === "ar" 
                    ? "اربط النظام ببوت تليجرام لترحيل الفواتير ممسوحة ضوئياً مباشرة من هاتفك."
                    : "Connect the system to a Telegram bot to post scanned invoices directly from your phone."}
                </p>
                
                <div className="space-y-0.5">
                  <label className="block text-[10px] font-medium gold-text">
                    {language === "ar" ? "مفتاح البوت (Bot Token):" : "Telegram Bot Token:"}
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
                    value={telegramToken}
                    onChange={(e) => setTelegramToken(e.target.value)}
                    className="w-full bg-black/40 border border-white/20 text-white px-2 py-1 text-xs rounded-lg outline-none focus:border-yellow-500 transition-colors"
                  />
                </div>

                <div className="text-[10px] text-white/50 leading-relaxed bg-black/20 p-2 rounded-lg border border-white/5">
                  <p className="font-semibold text-white/70 mb-0.5">{language === "ar" ? "🛠️ خطوات إنشاء البوت:" : "🛠️ Steps to create:"}</p>
                  <p>1. {language === "ar" ? "ابحث عن @BotFather في تليجرام." : "Search for @BotFather in Telegram."}</p>
                  <p>2. {language === "ar" ? "أرسل الأمر /newbot واتبع التعليمات لإنشاء بوت جديد." : "Send /newbot and follow instructions to create a bot."}</p>
                  <p>3. {language === "ar" ? "انسخ رمز التوكن (HTTP API Token) والصقه هنا." : "Copy the HTTP API Token and paste it here."}</p>
                </div>

                {telegramErrorMsg && (
                  <p className="text-red-400 text-[10px] bg-red-500/10 p-1.5 rounded border border-red-500/20 font-bold">
                    ⚠️ {telegramErrorMsg}
                  </p>
                )}
                {telegramSuccessMsg && (
                  <p className="text-green-400 text-[10px] bg-green-500/10 p-1.5 rounded border border-green-500/20 font-bold">
                    ✅ {telegramSuccessMsg}
                  </p>
                )}

                <button
                  type="submit"
                  disabled={telegramLoading || !telegramToken}
                  className="w-full cursor-pointer bg-gradient-to-r from-amber-500 to-yellow-600 hover:from-amber-600 hover:to-yellow-700 text-black font-bold py-1 px-3 rounded-lg text-xs transition-all shadow-md active:scale-[0.98] disabled:opacity-50"
                >
                  {telegramLoading ? (language === "ar" ? "جاري التفعيل..." : "Activating...") : (language === "ar" ? "تفعيل وحفظ البوت" : "Activate & Save Bot")}
                </button>
              </form>
            )}
          </div>

          {/* Test results display */}
          {testResult && testResult.connected && (
            <div className="wood-card bg-green-950/10 border-green-500/20">
              <h3 className="text-xl font-bold text-green-400 mb-2">{t("erp.diagnostics")}</h3>
              <div className="text-xs space-y-2 text-white/70">
                <p>
                  <strong>{t("erp.sessionUid")}</strong> {testResult.uid}
                </p>
                <p>
                  <strong>{t("erp.authUser")}</strong> {testResult.user?.name} ({testResult.user?.login})
                </p>
                <p>
                  <strong>{t("erp.engine")}</strong> {testResult.odoo_version?.server_version}
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
