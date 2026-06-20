"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { API_BASE_URL } from "@/lib/api";
import { useLanguage } from "@/lib/LanguageContext";

type AssetTab =
  | "accounts"
  | "journals"
  | "taxes"
  | "partners"
  | "cost_centers"
  | "products"
  | "employees";

export default function ERPDiscoveryPage() {
  const { t } = useLanguage();

  const [kb, setKb] = useState<any>(null);
  const [status, setStatus] = useState<"idle" | "discovering" | "success" | "error">("idle");
  const [activeTab, setActiveTab] = useState<AssetTab>("accounts");
  const [message, setMessage] = useState("");
  const [searchTerm, setSearchTerm] = useState("");

  const fetchDiscoveryData = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/discovery`);
      if (response.ok) {
        const data = await response.json();
        setKb(data);
        setStatus("success");
      } else {
        setStatus("idle");
      }
    } catch (err) {
      console.error("Failed to load discovery database:", err);
      setStatus("idle");
    }
  };

  useEffect(() => {
    fetchDiscoveryData();
  }, []);

  const handleTriggerDiscovery = async () => {
    setStatus("discovering");
    setMessage("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/discover`, {
        method: "POST",
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || t("discovery.errorMsg"));
      }

      setMessage(t("discovery.successMsg"));
      fetchDiscoveryData();
    } catch (err: any) {
      setStatus("error");
      setMessage(err.message || t("discovery.errorMsg"));
    }
  };

  const getFilteredItems = (items: any[]) => {
    if (!items) return [];
    return items.filter((item: any) => {
      const query = searchTerm.toLowerCase();

      const nameStr = typeof item.name === "string" ? item.name : "";
      const codeStr = typeof item.code === "string" ? item.code : "";
      const defCodeStr = typeof item.default_code === "string" ? item.default_code : "";
      const emailStr = typeof item.email === "string" ? item.email : "";

      return (
        nameStr.toLowerCase().includes(query) ||
        codeStr.toLowerCase().includes(query) ||
        defCodeStr.toLowerCase().includes(query) ||
        emailStr.toLowerCase().includes(query)
      );
    });
  };

  const getTabLabel = (tab: AssetTab) => {
    switch (tab) {
      case "accounts":
        return t("discovery.accounts");
      case "journals":
        return t("discovery.journals");
      case "taxes":
        return t("discovery.taxes");
      case "partners":
        return t("discovery.partnersLabel");
      case "cost_centers":
        return t("discovery.costCenters");
      case "products":
        return t("discovery.productsLabel");
      case "employees":
        return t("discovery.employees");
    }
  };

  const getTabShortLabel = (tab: AssetTab) => {
    switch (tab) {
      case "accounts":
        return t("discovery.accounts");
      case "journals":
        return t("discovery.journals");
      case "taxes":
        return t("discovery.taxes");
      case "partners":
        return t("discovery.partners");
      case "cost_centers":
        return t("discovery.costCentersShort");
      case "products":
        return t("discovery.products");
      case "employees":
        return t("discovery.employees");
    }
  };

  return (
    <div className="fade-in p-4 w-full h-full flex flex-col justify-start overflow-hidden text-[11px]">
      {/* Navigation and Title */}
      <div className="mb-2 flex items-center justify-between">
        <div>
          <Link
            href="/erp"
            className="gold-text text-[10px] tracking-widest hover:underline uppercase transition-all"
          >
            {t("discovery.back")}
          </Link>
          <h1 className="mt-0.5 text-xl font-bold">{t("discovery.title")}</h1>
          <p className="text-[11px] text-white/70 font-serif">
            {t("discovery.desc")}
          </p>
        </div>

        {/* Action Button */}
        <div>
          <button
            onClick={handleTriggerDiscovery}
            disabled={status === "discovering"}
            className="cursor-pointer bg-gradient-to-r from-amber-500 to-yellow-600 hover:from-amber-600 hover:to-yellow-700 text-black font-bold py-1.5 px-3 rounded-lg text-xs transition-all shadow-[0_0_20px_rgba(217,164,65,0.25)] active:scale-[0.98] disabled:opacity-50 flex items-center gap-1.5"
          >
            {status === "discovering" ? (
              <>
                <span className="w-3.5 h-3.5 border border-black border-t-transparent rounded-full animate-spin" />
                {t("discovery.discovering")}
              </>
            ) : (
              t("discovery.triggerBtn")
            )}
          </button>
        </div>
      </div>

      <div className="gold-divider mb-4" />

      {/* Discovery Logs / Messages */}
      {message && (
        <div
          className={`mb-6 p-4 rounded-xl text-sm border ${
            status === "error"
              ? "bg-red-500/10 border-red-500/30 text-red-300"
              : "bg-green-500/10 border-green-500/30 text-green-300"
          }`}
        >
          {status === "error" ? "❌ " : "✅ "} {message}
        </div>
      )}

      {/* Discovery Dashboard */}
      {kb ? (
        <div className="flex-1 min-h-0 flex flex-col gap-3 overflow-hidden">
          {/* Metadata & Discovery Summary Cards */}
          <div className="grid gap-2 md:grid-cols-4 lg:grid-cols-7 text-[11px]">
            <div className="wood-card !p-2.5 col-span-2">
              <p className="text-[10px] text-white/50">{t("discovery.discoveredSource")}</p>
              <h3 className="text-sm font-bold gold-text mt-0.5 truncate">
                {kb.metadata?.companies?.[0]?.name || "Odoo Instance"}
              </h3>
              <p className="text-[9px] text-white/40 truncate">{kb.metadata?.url}</p>
            </div>

            <div
              className={`wood-card !p-2.5 cursor-pointer transition-all ${
                activeTab === "accounts" ? "border-yellow-500 shadow-md" : "border-white/10"
              }`}
              onClick={() => setActiveTab("accounts")}
            >
              <p className="text-[10px] text-white/50">{t("discovery.accounts")}</p>
              <h3 className="text-lg font-bold mt-0.5 gold-text">{kb.accounts?.length || 0}</h3>
            </div>

            <div
              className={`wood-card !p-2.5 cursor-pointer transition-all ${
                activeTab === "journals" ? "border-yellow-500 shadow-md" : "border-white/10"
              }`}
              onClick={() => setActiveTab("journals")}
            >
              <p className="text-[10px] text-white/50">{t("discovery.journals")}</p>
              <h3 className="text-lg font-bold mt-0.5 gold-text">{kb.journals?.length || 0}</h3>
            </div>

            <div
              className={`wood-card !p-2.5 cursor-pointer transition-all ${
                activeTab === "taxes" ? "border-yellow-500 shadow-md" : "border-white/10"
              }`}
              onClick={() => setActiveTab("taxes")}
            >
              <p className="text-[10px] text-white/50">{t("discovery.taxes")}</p>
              <h3 className="text-lg font-bold mt-0.5 gold-text">{kb.taxes?.length || 0}</h3>
            </div>

            <div
              className={`wood-card !p-2.5 cursor-pointer transition-all ${
                activeTab === "partners" ? "border-yellow-500 shadow-md" : "border-white/10"
              }`}
              onClick={() => setActiveTab("partners")}
            >
              <p className="text-[10px] text-white/50">{t("discovery.partners")}</p>
              <h3 className="text-lg font-bold mt-0.5 gold-text">{kb.partners?.length || 0}</h3>
            </div>

            <div
              className={`wood-card !p-2.5 cursor-pointer transition-all ${
                activeTab === "products" ? "border-yellow-500 shadow-md" : "border-white/10"
              }`}
              onClick={() => setActiveTab("products")}
            >
              <p className="text-[10px] text-white/50">{t("discovery.products")}</p>
              <h3 className="text-lg font-bold mt-0.5 gold-text">{kb.products?.length || 0}</h3>
            </div>
          </div>

          {/* Search and Tabs Header */}
          <div className="flex flex-col md:flex-row gap-2 items-center justify-between bg-black/30 p-2 rounded-xl border border-white/5 backdrop-blur-sm">
            {/* Tabs List */}
            <div className="flex flex-wrap gap-1.5">
              {(
                [
                  "accounts",
                  "journals",
                  "taxes",
                  "partners",
                  "cost_centers",
                  "products",
                  "employees",
                ] as AssetTab[]
              ).map((tab) => (
                <button
                  key={tab}
                  onClick={() => {
                    setActiveTab(tab);
                    setSearchTerm("");
                  }}
                  className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all ${
                    activeTab === tab
                      ? "bg-amber-500 text-black shadow-md"
                      : "text-white/60 hover:text-white hover:bg-white/5"
                  }`}
                >
                  {getTabShortLabel(tab)} ({kb[tab]?.length || 0})
                </button>
              ))}
            </div>

            {/* Live Search Bar */}
            <div className="w-full md:w-60">
              <input
                type="text"
                placeholder={t("discovery.search")}
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full bg-black/40 border border-white/20 text-white px-3 py-1 text-xs rounded-lg outline-none focus:border-yellow-500 transition-colors"
              />
            </div>
          </div>

          {/* Details Table */}
          <div className="flex-1 min-h-0 wood-panel rounded-xl overflow-hidden flex flex-col">
            <div className="p-3 border-b border-white/10 flex justify-between items-center">
              <h3 className="text-sm font-bold gold-text">{getTabLabel(activeTab)}</h3>
              <span className="text-[10px] text-white/40">{t("discovery.showingLive")}</span>
            </div>

            <div className="flex-1 overflow-auto">
              <table className="w-full text-left border-collapse text-sm">
                <thead>
                  <tr className="bg-black/30 text-white/50 uppercase tracking-wider text-xs border-b border-white/10">
                    {activeTab === "accounts" && (
                      <>
                        <th className="p-4 font-semibold">{t("discovery.thCode")}</th>
                        <th className="p-4 font-semibold">{t("discovery.thName")}</th>
                        <th className="p-4 font-semibold">{t("discovery.thType")}</th>
                        <th className="p-4 font-semibold">{t("discovery.thReconcile")}</th>
                      </>
                    )}
                    {activeTab === "journals" && (
                      <>
                        <th className="p-4 font-semibold">{t("discovery.thJournalCode")}</th>
                        <th className="p-4 font-semibold">{t("discovery.thJournalName")}</th>
                        <th className="p-4 font-semibold">{t("discovery.thJournalType")}</th>
                        <th className="p-4 font-semibold">{t("discovery.thStatus")}</th>
                      </>
                    )}
                    {activeTab === "taxes" && (
                      <>
                        <th className="p-4 font-semibold">{t("discovery.thTaxName")}</th>
                        <th className="p-4 font-semibold">{t("discovery.thTaxRate")}</th>
                        <th className="p-4 font-semibold">{t("discovery.thRateType")}</th>
                        <th className="p-4 font-semibold">{t("discovery.thUsage")}</th>
                        <th className="p-4 font-semibold">{t("discovery.thIncluded")}</th>
                      </>
                    )}
                    {activeTab === "partners" && (
                      <>
                        <th className="p-4 font-semibold">{t("discovery.thName")}</th>
                        <th className="p-4 font-semibold">{t("discovery.thEmail")}</th>
                        <th className="p-4 font-semibold">{t("discovery.thPhone")}</th>
                        <th className="p-4 font-semibold">{t("discovery.thVat")}</th>
                        <th className="p-4 font-semibold">{t("discovery.thPartnerType")}</th>
                      </>
                    )}
                    {activeTab === "cost_centers" && (
                      <>
                        <th className="p-4 font-semibold">{t("discovery.thCostCenterCode")}</th>
                        <th className="p-4 font-semibold">{t("discovery.thCostCenterName")}</th>
                        <th className="p-4 font-semibold">{t("discovery.thStatus")}</th>
                      </>
                    )}
                    {activeTab === "products" && (
                      <>
                        <th className="p-4 font-semibold">{t("discovery.thProductCode")}</th>
                        <th className="p-4 font-semibold">{t("discovery.thProductName")}</th>
                        <th className="p-4 font-semibold">{t("discovery.thSalesPrice")}</th>
                        <th className="p-4 font-semibold">{t("discovery.thStandardCost")}</th>
                      </>
                    )}
                    {activeTab === "employees" && (
                      <>
                        <th className="p-4 font-semibold">{t("discovery.thEmployeeName")}</th>
                        <th className="p-4 font-semibold">{t("discovery.thWorkEmail")}</th>
                        <th className="p-4 font-semibold">{t("discovery.thWorkPhone")}</th>
                      </>
                    )}
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {getFilteredItems(kb[activeTab])?.length > 0 ? (
                    getFilteredItems(kb[activeTab]).map((item: any, idx: number) => (
                      <tr key={idx} className="hover:bg-white/5 transition-colors">
                        {activeTab === "accounts" && (
                          <>
                            <td className="p-4 font-mono gold-text font-semibold">{item.code}</td>
                            <td className="p-4 font-medium text-white">{item.name}</td>
                            <td className="p-4 text-white/70 capitalize">{item.account_type}</td>
                            <td className="p-4">
                              <span
                                className={`text-xs px-2 py-0.5 rounded ${
                                  item.reconcile
                                    ? "bg-green-500/10 text-green-300 border border-green-500/20"
                                    : "bg-white/5 text-white/50"
                                  }`}
                              >
                                {item.reconcile ? t("discovery.enabled") : t("discovery.disabled")}
                              </span>
                            </td>
                          </>
                        )}
                        {activeTab === "journals" && (
                          <>
                            <td className="p-4 font-mono gold-text font-semibold">{item.code}</td>
                            <td className="p-4 font-medium text-white">{item.name}</td>
                            <td className="p-4 text-white/70 capitalize">{item.type}</td>
                            <td className="p-4">
                              <span
                                className={`text-xs px-2 py-0.5 rounded ${
                                  item.active
                                    ? "bg-green-500/10 text-green-300 border border-green-500/20"
                                    : "bg-red-500/10 text-red-300 border border-red-500/20"
                                }`}
                              >
                                {item.active ? t("discovery.active") : t("discovery.inactive")}
                              </span>
                            </td>
                          </>
                        )}
                        {activeTab === "taxes" && (
                          <>
                            <td className="p-4 font-medium text-white">{item.name}</td>
                            <td className="p-4 font-semibold text-white">
                              {item.amount_type === "percent"
                                ? `${item.amount}%`
                                : item.amount}
                            </td>
                            <td className="p-4 text-white/70 capitalize">{item.amount_type}</td>
                            <td className="p-4 text-white/70 capitalize">{item.type_tax_use}</td>
                            <td className="p-4">
                              <span
                                className={`text-xs px-2 py-0.5 rounded ${
                                  item.price_include
                                    ? "bg-green-500/10 text-green-300 border border-green-500/20"
                                    : "bg-white/5 text-white/50"
                                }`}
                              >
                                {item.price_include ? t("discovery.included") : t("discovery.excluded")}
                              </span>
                            </td>
                          </>
                        )}
                        {activeTab === "partners" && (
                          <>
                            <td className="p-4 font-medium text-white">{item.name}</td>
                            <td className="p-4 text-white/70">{item.email || "N/A"}</td>
                            <td className="p-4 text-white/70">{item.phone || "N/A"}</td>
                            <td className="p-4 font-mono text-white/70">{item.vat || "N/A"}</td>
                            <td className="p-4 text-white/70">
                              {item.is_company ? t("discovery.company") : t("discovery.individual")}
                            </td>
                          </>
                        )}
                        {activeTab === "cost_centers" && (
                          <>
                            <td className="p-4 font-mono gold-text font-semibold">{item.code || idx + 1}</td>
                            <td className="p-4 font-medium text-white">{item.name}</td>
                            <td className="p-4">
                              <span
                                className={`text-xs px-2 py-0.5 rounded ${
                                  item.active
                                    ? "bg-green-500/10 text-green-300 border border-green-500/20"
                                    : "bg-white/5 text-white/50"
                                }`}
                              >
                                {item.active ? t("discovery.active") : t("discovery.inactive")}
                              </span>
                            </td>
                          </>
                        )}
                        {activeTab === "products" && (
                          <>
                            <td className="p-4 font-mono gold-text font-semibold">{item.default_code || "N/A"}</td>
                            <td className="p-4 font-medium text-white">{item.name}</td>
                            <td className="p-4 font-semibold text-white">{item.lst_price}</td>
                            <td className="p-4 text-white/70">{item.standard_price}</td>
                          </>
                        )}
                        {activeTab === "employees" && (
                          <>
                            <td className="p-4 font-medium text-white">{item.name}</td>
                            <td className="p-4 text-white/70">{item.work_email || "N/A"}</td>
                            <td className="p-4 text-white/70">{item.work_phone || "N/A"}</td>
                          </>
                        )}
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={5} className="p-8 text-center text-white/40 italic">
                        {t("discovery.noRecords")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : (
        /* Empty State */
        <div className="wood-panel rounded-[32px] p-12 text-center max-w-2xl mx-auto space-y-6">
          <div className="w-20 h-20 mx-auto rounded-full bg-yellow-500/10 border border-yellow-500/30 flex items-center justify-center">
            <span className="text-4xl">🔍</span>
          </div>
          <h2 className="text-3xl font-bold gold-text">{t("discovery.emptyStateTitle")}</h2>
          <p className="text-white/60 font-serif">
            {t("discovery.emptyStateDesc")}
          </p>
          <button
            onClick={handleTriggerDiscovery}
            disabled={status === "discovering"}
            className="cursor-pointer bg-gradient-to-r from-amber-500 to-yellow-600 hover:from-amber-600 hover:to-yellow-700 text-black font-bold py-4 px-8 rounded-xl transition-all shadow-lg inline-flex items-center gap-2"
          >
            {status === "discovering" ? (
              <>
                <span className="w-5 h-5 border-2 border-black border-t-transparent rounded-full animate-spin" />
                {t("discovery.discovering")}
              </>
            ) : (
              t("discovery.startDiscoveryBtn")
            )}
          </button>
        </div>
      )}
    </div>
  );
}
