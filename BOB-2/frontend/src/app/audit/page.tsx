"use client";

import React, { useState, useEffect, useRef } from "react";
import { useLanguage } from "@/lib/LanguageContext";
import { useCompany } from "@/lib/CompanyContext";
import { API_BASE_URL } from "@/lib/api";

interface Attachment {
  id: number;
  name: string;
}

interface MoveLine {
  id: number;
  account_code: string;
  account_name: string;
  name: string;
  debit: number;
  credit: number;
}

interface MoveTransaction {
  id: number;
  name: string;
  ref: string;
  date: string;
  amount_total: number;
  partner_name: string;
  journal_name: string;
  attachments: Attachment[];
  lines?: MoveLine[];
}

export default function AuditPage() {
  const { t, language } = useLanguage();
  const { selectedCompanyId } = useCompany();
  const fileInputRefs = useRef<Record<number, HTMLInputElement | null>>({});

  // Filter States
  const [accounts, setAccounts] = useState<{ id: number; code: string; name: string }[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  
  // Data States
  const [attachedMoves, setAttachedMoves] = useState<MoveTransaction[]>([]);
  const [notAttachedMoves, setNotAttachedMoves] = useState<MoveTransaction[]>([]);
  const [summary, setSummary] = useState({ attached_count: 0, not_attached_count: 0, total_count: 0 });
  
  // Status States
  const [loading, setLoading] = useState(false);
  const [uploadingMoveId, setUploadingMoveId] = useState<number | null>(null);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [searched, setSearched] = useState(false);

  const fetchAccounts = async () => {
    try {
      const companyParam = selectedCompanyId ? `?company_id=${selectedCompanyId}` : "";
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/accounts${companyParam}`);
      if (response.ok) {
        const data = await response.json();
        setAccounts(data);
      }
    } catch (err) {
      console.error("Failed to fetch accounts:", err);
    }
  };

  useEffect(() => {
    fetchAccounts();
  }, [selectedCompanyId]);

  const handleDetectAttachments = async () => {
    setLoading(true);
    setMessage(null);
    try {
      const payload = {
        company_id: selectedCompanyId ?? 1,
        date_from: dateFrom || null,
        date_to: dateTo || null,
        account_id: selectedAccountId || null,
      };

      const response = await fetch(`${API_BASE_URL}/api/v1/erp/detect-attachments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error("Failed to search attachments");
      }

      const data = await response.json();
      if (data.status === "success") {
        setAttachedMoves(data.attached || []);
        setNotAttachedMoves(data.not_attached || []);
        setSummary(data.summary || { attached_count: 0, not_attached_count: 0, total_count: 0 });
        setSearched(true);
      } else {
        setMessage({ type: "error", text: "حدث خطأ أثناء معالجة البيانات من Odoo." });
      }
    } catch (err: any) {
      console.error(err);
      setMessage({ type: "error", text: "فشل الاتصال بخادم Odoo للتحقق من المرفقات." });
    } finally {
      setLoading(false);
    }
  };

  const handleFileUploadClick = (moveId: number) => {
    fileInputRefs.current[moveId]?.click();
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>, moveId: number) => {
    if (!e.target.files || e.target.files.length === 0) return;
    const file = e.target.files[0];
    
    setUploadingMoveId(moveId);
    setMessage(null);

    const formData = new FormData();
    formData.append("file", file);
    formData.append("move_id", moveId.toString());

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/attach-document`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        throw new Error("Failed to upload attachment");
      }

      const data = await response.json();
      if (data.status === "success") {
        // Find the transaction in notAttachedMoves
        const transaction = notAttachedMoves.find((m) => m.id === moveId);
        if (transaction) {
          // Fetch its complete details (lines) as well if not already present
          const updatedTransaction: MoveTransaction = {
            ...transaction,
            attachments: [...transaction.attachments, { id: data.attachment_id || 9999, name: file.name }],
          };
          setNotAttachedMoves((prev) => prev.filter((m) => m.id !== moveId));
          setAttachedMoves((prev) => [updatedTransaction, ...prev]);
          setSummary((prev) => ({
            ...prev,
            attached_count: prev.attached_count + 1,
            not_attached_count: prev.not_attached_count - 1,
          }));
        }
        setMessage({ type: "success", text: `تم ربط الملف "${file.name}" بنجاح بالمعاملة!` });
      } else {
        setMessage({ type: "error", text: data.message || "فشل تحميل المستند." });
      }
    } catch (err) {
      console.error(err);
      setMessage({ type: "error", text: "حدث خطأ أثناء الاتصال بالخادم لربط الملف." });
    } finally {
      setUploadingMoveId(null);
      // Clear file input value
      e.target.value = "";
    }
  };

  const handlePrint = (move: MoveTransaction) => {
    const printWindow = window.open("", "_blank");
    if (!printWindow) {
      alert("يرجى السماح بالنوافذ المنبثقة لطباعة القيود والمستندات.");
      return;
    }

    const totalDebit = move.lines ? move.lines.reduce((sum, line) => sum + line.debit, 0) : 0;
    const totalCredit = move.lines ? move.lines.reduce((sum, line) => sum + line.credit, 0) : 0;

    const linesHTML = move.lines && move.lines.length > 0 
      ? move.lines.map(line => `
          <tr>
            <td style="padding: 10px; border: 1px solid #ddd; text-align: right; font-family: 'Cairo', sans-serif;">${line.account_code || ""}</td>
            <td style="padding: 10px; border: 1px solid #ddd; text-align: right; font-family: 'Cairo', sans-serif;">${line.account_name || ""}</td>
            <td style="padding: 10px; border: 1px solid #ddd; text-align: right; font-family: 'Cairo', sans-serif;">${line.name || ""}</td>
            <td style="padding: 10px; border: 1px solid #ddd; text-align: center; font-weight: bold; color: #1e3a8a; font-family: 'Cairo', sans-serif;">
              ${line.debit > 0 ? line.debit.toLocaleString(undefined, { minimumFractionDigits: 2 }) + " ر.س" : "-"}
            </td>
            <td style="padding: 10px; border: 1px solid #ddd; text-align: center; font-weight: bold; color: #1e3a8a; font-family: 'Cairo', sans-serif;">
              ${line.credit > 0 ? line.credit.toLocaleString(undefined, { minimumFractionDigits: 2 }) + " ر.س" : "-"}
            </td>
          </tr>
        `).join("")
      : `<tr><td colspan="5" style="padding: 15px; border: 1px solid #ddd; text-align: center; color: #777; font-family: 'Cairo', sans-serif;">لا توجد تفاصيل بنود متوفرة لهذا القيد.</td></tr>`;

    const attachmentsHTML = move.attachments && move.attachments.length > 0
      ? move.attachments.map(att => {
          const fileUrl = `${API_BASE_URL}/api/v1/erp/attachment/${att.id}`;
          const isPdf = att.name.toLowerCase().endsWith(".pdf");
          if (isPdf) {
            return `
              <div style="margin-top: 30px; page-break-before: always; text-align: center;">
                <h3 style="color: #333; margin-bottom: 15px; font-family: 'Cairo', sans-serif; font-size: 13px;">مستند مرفق PDF: ${att.name}</h3>
                <iframe src="${fileUrl}" style="width: 100%; height: 850px; border: 2px solid #ddd; border-radius: 8px;"></iframe>
              </div>
            `;
          } else {
            return `
              <div style="margin-top: 30px; page-break-before: always; text-align: center;">
                <h3 style="color: #333; margin-bottom: 15px; font-family: 'Cairo', sans-serif; font-size: 13px;">مستند مرفق صورة: ${att.name}</h3>
                <img src="${fileUrl}" style="max-width: 100%; max-height: 800px; border: 2px solid #ddd; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);" />
              </div>
            `;
          }
        }).join("")
      : "";

    printWindow.document.write(`
      <!DOCTYPE html>
      <html dir="rtl" lang="ar">
      <head>
        <meta charset="utf-8">
        <title>طباعة قيد محاسبي - ${move.name || "معاملة"}</title>
        <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap" rel="stylesheet">
        <style>
          body {
            font-family: 'Cairo', sans-serif;
            margin: 30px;
            color: #333;
            background-color: #fff;
          }
          .header-table {
            width: 100%;
            margin-bottom: 20px;
            border-collapse: collapse;
          }
          .header-table td {
            padding: 8px;
            vertical-align: top;
            font-size: 12px;
          }
          .voucher-title {
            text-align: center;
            font-size: 20px;
            font-weight: 800;
            color: #b8860b;
            margin-bottom: 25px;
            border-bottom: 3px double #b8860b;
            padding-bottom: 10px;
          }
          .signature-section {
            margin-top: 40px;
            width: 100%;
            border-collapse: collapse;
          }
          .signature-section td {
            text-align: center;
            padding: 15px;
            font-size: 11px;
            font-weight: bold;
            color: #555;
            width: 33.33%;
          }
          .signature-line {
            width: 150px;
            border-bottom: 1px solid #999;
            margin: 35px auto 5px auto;
          }
          @media print {
            .no-print { display: none; }
            body { margin: 20px; }
          }
        </style>
      </head>
      <body>
        <!-- Print Trigger Bar (non-printable) -->
        <div class="no-print" style="background: #f3f4f6; padding: 12px 20px; margin-bottom: 30px; display: flex; justify-content: space-between; align-items: center; border-radius: 8px; border: 1px solid #e5e7eb;">
          <span style="font-size: 12px; font-weight: bold; color: #4b5563;">جاهز للطباعة. يرجى الضغط على زر الطباعة المجاور:</span>
          <button onclick="window.print()" style="background: #b8860b; border: none; color: white; padding: 8px 16px; border-radius: 6px; font-size: 12px; font-weight: bold; cursor: pointer; font-family: 'Cairo', sans-serif; box-shadow: 0 2px 4px rgba(0,0,0,0.15);">طباعة المستند والقيد</button>
        </div>

        <!-- Voucher Content -->
        <div class="voucher-title">سند قيد محاسبي / Journal Entry Voucher</div>

        <table class="header-table">
          <tr>
            <td style="width: 50%;">رقم القيد: <strong style="color:#000;">${move.name || `قيد #${move.id}`}</strong></td>
            <td style="width: 50%;">تاريخ القيد: <strong style="color:#000;">${move.date}</strong></td>
          </tr>
          <tr>
            <td>دفتر اليومية: <strong style="color:#000;">${move.journal_name}</strong></td>
            <td>المرجع/البيان: <strong style="color:#000;">${move.ref || "-"}</strong></td>
          </tr>
          <tr>
            <td colspan="2">الشريك (المورد/العميل): <strong style="color:#000;">${move.partner_name || "غير محدد"}</strong></td>
          </tr>
        </table>

        <!-- Lines Table -->
        <table style="width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 12px;">
          <thead>
            <tr style="background-color: #f8fafc;">
              <th style="padding: 10px; border: 1px solid #ddd; text-align: right; width: 15%;">كود الحساب</th>
              <th style="padding: 10px; border: 1px solid #ddd; text-align: right; width: 30%;">الحساب المحاسبي</th>
              <th style="padding: 10px; border: 1px solid #ddd; text-align: right; width: 25%;">البيان / الوصف</th>
              <th style="padding: 10px; border: 1px solid #ddd; text-align: center; width: 15%;">مدين (Debit)</th>
              <th style="padding: 10px; border: 1px solid #ddd; text-align: center; width: 15%;">دائن (Credit)</th>
            </tr>
          </thead>
          <tbody>
            ${linesHTML}
            <tr style="background-color: #f1f5f9; font-weight: bold;">
              <td colspan="3" style="padding: 12px; border: 1px solid #ddd; text-align: left; font-size: 13px;">المجموع الإجمالي:</td>
              <td style="padding: 12px; border: 1px solid #ddd; text-align: center; font-size: 13px; color: #1e3a8a;">
                ${totalDebit.toLocaleString(undefined, { minimumFractionDigits: 2 })} ر.س
              </td>
              <td style="padding: 12px; border: 1px solid #ddd; text-align: center; font-size: 13px; color: #1e3a8a;">
                ${totalCredit.toLocaleString(undefined, { minimumFractionDigits: 2 })} ر.س
              </td>
            </tr>
          </tbody>
        </table>

        <!-- Signatures section -->
        <table class="signature-section">
          <tr>
            <td>
              <div class="signature-line"></div>
              <span>أعده (المحاسب)</span>
            </td>
            <td>
              <div class="signature-line"></div>
              <span>راجعه (المدير المالي)</span>
            </td>
            <td>
              <div class="signature-line"></div>
              <span>دققه (مدقق الحسابات المالي)</span>
            </td>
          </tr>
        </table>

        <!-- Embedded Attachments Section -->
        ${attachmentsHTML}
        
      </body>
      </html>
    `);

    printWindow.document.close();
  };

  return (
    <div className="fade-in p-6 h-full w-full flex flex-col justify-start items-center overflow-y-auto selection:bg-[#d9a441]/30">
      
      {/* Top Banner Header */}
      <div className="w-full flex justify-between items-center mb-6 border-b border-white/10 pb-4">
        <div>
          <h1 className="text-xl font-bold bg-gradient-to-r from-amber-300 via-yellow-500 to-amber-200 bg-clip-text text-transparent drop-shadow-[0_0_8px_rgba(217,164,65,0.4)]">
            غرفة التحكم بالتدقيق وكشف المرفقات
          </h1>
          <p className="text-xs text-gray-400 mt-1">
            البحث في النظام وتصنيف المعاملات حسب وجود مرفقات وإثباتات ورقية
          </p>
        </div>
      </div>

      {/* Control Panel Filter bar */}
      <div className="w-full wood-panel p-5 rounded-2xl border border-yellow-500/10 shadow-lg flex flex-wrap gap-4 items-end justify-between mb-6">
        
        {/* Left Side: Filter inputs */}
        <div className="flex flex-wrap gap-4 flex-1">
          
          {/* Account Filter */}
          <div className="flex flex-col gap-1.5 min-w-[240px] flex-1">
            <label className="text-[11px] font-bold text-gray-400 flex items-center gap-1.5">
              <span>📂</span>
              <span>فلتر الحسابات المحاسبية:</span>
            </label>
            <select
              value={selectedAccountId || ""}
              onChange={(e) => setSelectedAccountId(e.target.value ? parseInt(e.target.value) : null)}
              className="h-10 px-3 bg-black/40 border border-[#d9a441]/30 rounded-lg text-xs font-semibold text-white focus:outline-none focus:border-[#d9a441] transition-all cursor-pointer"
            >
              <option value="">جميع الحسابات (بدون فلترة)</option>
              {accounts.map((acc) => (
                <option key={acc.id} value={acc.id}>
                  {acc.code} - {acc.name}
                </option>
              ))}
            </select>
          </div>

          {/* Date Range: Date From */}
          <div className="flex flex-col gap-1.5 min-w-[150px]">
            <label className="text-[11px] font-bold text-gray-400 flex items-center gap-1.5">
              <span>📅</span>
              <span>من تاريخ:</span>
            </label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="h-10 px-3 bg-black/40 border border-[#d9a441]/30 rounded-lg text-xs font-semibold text-white focus:outline-none focus:border-[#d9a441] transition-all cursor-pointer"
            />
          </div>

          {/* Date Range: Date To */}
          <div className="flex flex-col gap-1.5 min-w-[150px]">
            <label className="text-[11px] font-bold text-gray-400 flex items-center gap-1.5">
              <span>📅</span>
              <span>إلى تاريخ:</span>
            </label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="h-10 px-3 bg-black/40 border border-[#d9a441]/30 rounded-lg text-xs font-semibold text-white focus:outline-none focus:border-[#d9a441] transition-all cursor-pointer"
            />
          </div>

        </div>

        {/* Right Side: Main Search Button */}
        <button
          onClick={handleDetectAttachments}
          disabled={loading}
          className="px-6 h-10 rounded-lg bg-gradient-to-br from-[#221205] to-[#0f0701] border border-[#d9a441] text-[#d9a441] text-xs font-bold
                     shadow-[inset_0_1px_2px_rgba(0,0,0,0.9),_0_0_10px_rgba(217,164,65,0.6)]
                     hover:shadow-[inset_0_1px_2px_rgba(0,0,0,0.9),_0_0_20px_rgba(217,164,65,0.9)]
                     hover:scale-102 active:scale-98 transition-all duration-300 disabled:opacity-50 flex items-center gap-2 cursor-pointer"
        >
          {loading ? (
            <>
              <div className="w-3.5 h-3.5 border-2 border-[#d9a441]/30 border-t-[#d9a441] rounded-full animate-spin"></div>
              <span>جاري الفحص...</span>
            </>
          ) : (
            <>
              <span>🔍</span>
              <span>الكشف عن المرفقات</span>
            </>
          )}
        </button>
      </div>

      {/* Messages banner */}
      {message && (
        <div 
          className={`w-full p-3.5 rounded-xl border mb-6 text-xs font-medium flex items-center gap-2.5 shadow-md fade-in
                     ${message.type === "success" 
                       ? "bg-green-500/10 border-green-500/20 text-green-400 shadow-green-950/10" 
                       : "bg-red-500/10 border-red-500/20 text-red-400 shadow-red-950/10"
                     }`}
        >
          <span>{message.type === "success" ? "✅" : "⚠️"}</span>
          <span>{message.text}</span>
        </div>
      )}

      {/* Summary Stats Row */}
      {searched && (
        <div className="w-full grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
          <div className="wood-panel p-4 rounded-xl border border-white/5 flex flex-col justify-between">
            <span className="text-[10px] font-bold text-gray-400">إجمالي المعاملات المفحوصة</span>
            <span className="text-2xl font-extrabold text-white mt-1">{summary.total_count}</span>
          </div>
          <div className="wood-panel p-4 rounded-xl border border-green-500/10 flex flex-col justify-between">
            <span className="text-[10px] font-bold text-green-400">معاملات بمرفقات ومستندات</span>
            <span className="text-2xl font-extrabold text-green-400 mt-1">{summary.attached_count}</span>
          </div>
          <div className="wood-panel p-4 rounded-xl border border-red-500/10 flex flex-col justify-between">
            <span className="text-[10px] font-bold text-red-400">معاملات بدون مرفقات ومستندات</span>
            <span className="text-2xl font-extrabold text-red-400 mt-1">{summary.not_attached_count}</span>
          </div>
          <div className="wood-panel p-4 rounded-xl border border-[#d9a441]/10 flex flex-col justify-between">
            <span className="text-[10px] font-bold text-[#ffca5f]">نسبة تغطية المستندات</span>
            <span className="text-2xl font-extrabold text-[#ffca5f] mt-1">
              {summary.total_count > 0 ? ((summary.attached_count / summary.total_count) * 100).toFixed(1) : 0}%
            </span>
          </div>
        </div>
      )}

      {/* Two Column Layout: Attached vs Not Attached */}
      {searched ? (
        <div className="w-full grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
          
          {/* Column 1: Attached Group */}
          <div className="wood-panel rounded-2xl border border-green-500/15 overflow-hidden flex flex-col shadow-lg">
            
            {/* Header */}
            <div className="px-5 py-4 border-b border-white/10 bg-green-500/5 flex justify-between items-center">
              <h2 className="text-xs font-bold text-green-400 flex items-center gap-2">
                <span>📎</span>
                <span>مجموعة مرفق ({attachedMoves.length})</span>
              </h2>
            </div>

            {/* List */}
            <div className="p-4 flex flex-col gap-3 max-h-[500px] overflow-y-auto">
              {attachedMoves.length === 0 ? (
                <p className="text-center text-xs text-gray-500 py-8">لا توجد معاملات بمرفقات في هذه الفترة.</p>
              ) : (
                attachedMoves.map((move) => (
                  <div 
                    key={move.id} 
                    className="p-3.5 rounded-xl bg-black/20 border border-white/5 hover:border-green-500/20 transition-all flex flex-col gap-2"
                  >
                    <div className="flex justify-between items-start">
                      <div className="flex flex-col gap-0.5">
                        <span className="text-xs font-bold text-white flex items-center gap-1.5">
                          <span className="text-green-400">●</span>
                          {move.name || `قيد محاسبي #${move.id}`}
                        </span>
                        <span className="text-[9px] text-gray-400">
                          الدفتر: {move.journal_name} • التاريخ: {move.date}
                        </span>
                      </div>
                      <span className="text-xs font-extrabold text-green-400">
                        {move.amount_total.toLocaleString(undefined, { minimumFractionDigits: 2 })} ر.س
                      </span>
                    </div>

                    <div className="flex justify-between items-center text-[10px] text-gray-400 border-t border-white/5 pt-2 mt-1">
                      <span>العميل/المورد: <strong className="text-white">{move.partner_name || "غير محدد"}</strong></span>
                      <span>المرجع: <strong className="text-white">{move.ref || "-"}</strong></span>
                    </div>

                    {/* Attachments List and Print Button */}
                    <div className="mt-2 flex justify-between items-center border-t border-white/5 pt-2">
                      <div className="flex flex-wrap gap-1">
                        {move.attachments.map((att) => (
                          <div 
                            key={att.id}
                            className="bg-green-500/10 border border-green-500/20 text-green-400 px-1.5 py-0.5 rounded text-[8px] font-semibold flex items-center gap-1"
                          >
                            <span>📄</span>
                            <span className="truncate max-w-[90px]" title={att.name}>{att.name}</span>
                          </div>
                        ))}
                      </div>

                      <button
                        onClick={() => handlePrint(move)}
                        className="h-7 px-3.5 bg-yellow-500/10 border border-yellow-500/30 text-[#ffca5f] hover:bg-yellow-500/20 hover:border-yellow-500/50 rounded-md text-[10px] font-bold transition-all flex items-center gap-1.5 cursor-pointer"
                      >
                        <span>🖨️</span>
                        <span>طباعة المعاملة والمرفق</span>
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>

          </div>

          {/* Column 2: Not Attached Group */}
          <div className="wood-panel rounded-2xl border border-red-500/15 overflow-hidden flex flex-col shadow-lg">
            
            {/* Header */}
            <div className="px-5 py-4 border-b border-white/10 bg-red-500/5 flex justify-between items-center">
              <h2 className="text-xs font-bold text-red-400 flex items-center gap-2">
                <span>⚠️</span>
                <span>مجموعة من غير مرفق ({notAttachedMoves.length})</span>
              </h2>
            </div>

            {/* List */}
            <div className="p-4 flex flex-col gap-3 max-h-[500px] overflow-y-auto">
              {notAttachedMoves.length === 0 ? (
                <p className="text-center text-xs text-gray-500 py-8">كل المعاملات مستوفية ومرفق بها مستندات الإثبات!</p>
              ) : (
                notAttachedMoves.map((move) => (
                  <div 
                    key={move.id} 
                    className="p-3.5 rounded-xl bg-black/20 border border-white/5 hover:border-red-500/20 transition-all flex flex-col gap-2"
                  >
                    <div className="flex justify-between items-start">
                      <div className="flex flex-col gap-0.5">
                        <span className="text-xs font-bold text-white flex items-center gap-1.5">
                          <span className="text-red-400">●</span>
                          {move.name || `قيد محاسبي #${move.id}`}
                        </span>
                        <span className="text-[9px] text-gray-400">
                          الدفتر: {move.journal_name} • التاريخ: {move.date}
                        </span>
                      </div>
                      <span className="text-xs font-extrabold text-red-400">
                        {move.amount_total.toLocaleString(undefined, { minimumFractionDigits: 2 })} ر.س
                      </span>
                    </div>

                    <div className="flex justify-between items-center text-[10px] text-gray-400 border-t border-white/5 pt-2 mt-1">
                      <span>العميل/المورد: <strong className="text-white">{move.partner_name || "غير محدد"}</strong></span>
                      <span>المرجع: <strong className="text-white">{move.ref || "-"}</strong></span>
                    </div>

                    {/* Action button to attach doc */}
                    <div className="mt-2 flex justify-end gap-2 border-t border-white/5 pt-2">
                      <input
                        type="file"
                        ref={(el) => {
                          fileInputRefs.current[move.id] = el;
                        }}
                        onChange={(e) => handleFileChange(e, move.id)}
                        className="hidden"
                      />
                      <button
                        onClick={() => handleFileUploadClick(move.id)}
                        disabled={uploadingMoveId === move.id}
                        className="h-7 px-3 bg-red-500/10 border border-red-500/30 text-red-400 hover:bg-red-500/20 hover:border-red-500/50 rounded-md text-[10px] font-bold transition-all flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                      >
                        {uploadingMoveId === move.id ? (
                          <>
                            <div className="w-2.5 h-2.5 border border-red-400/30 border-t-red-400 rounded-full animate-spin"></div>
                            <span>جاري الرفع...</span>
                          </>
                        ) : (
                          <>
                            <span>📤</span>
                            <span>إرفاق مستند ورقي</span>
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>

          </div>

        </div>
      ) : (
        <div className="w-full wood-panel p-8 rounded-2xl border border-white/5 text-center flex flex-col items-center justify-center my-6 shadow-md select-none">
          <span className="text-3xl mb-3">📁</span>
          <h3 className="text-sm font-bold text-gray-300">لم يتم إجراء عملية الكشف بعد</h3>
          <p className="text-xs text-gray-500 mt-1 max-w-sm">
            حدد خيارات التصفية بالأعلى (النطاق الزمني والحساب المحاسبي)، ثم اضغط على زر &quot;الكشف عن المرفقات&quot; للبحث والتصنيف التلقائي.
          </p>
        </div>
      )}

    </div>
  );
}
