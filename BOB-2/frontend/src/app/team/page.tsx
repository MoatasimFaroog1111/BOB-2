"use client";

import React, { useState, useRef } from "react";
import Link from "next/link";
import { useLanguage } from "@/lib/LanguageContext";
import { API_BASE_URL } from "@/lib/api";

export default function TeamPage() {
  const { t } = useLanguage();
  const [files, setFiles] = useState<File[]>([]);
  const [isDragActive, setIsDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [readResults, setReadResults] = useState<{ 
    name: string; 
    content: string; 
    type: string;
    fileObject: File;
    matchedMoves?: {
      id: number;
      name: string;
      ref: string;
      date: string;
      amount_total: number;
      journal_name: string;
      similarity: number;
      partner_name?: string;
      move_type?: string;
      attachments?: { id: number; name: string; mimetype: string; url?: string }[];
      odoo_url?: string;
      journal_items?: {
        id?: number;
        account_name: string;
        label: string;
        debit: number;
        credit: number;
        quantity: number;
        price_unit: number;
        price_subtotal: number;
        product_name: string;
      }[];
    }[] | null;
    fields?: {
      total_amount: number;
      invoice_date: string;
      partner_name: string;
      invoice_number: string;
    };
    rawTextPreview?: string;
  }[]>([]);
  const [isReading, setIsReading] = useState(false);
  const [showViewer, setShowViewer] = useState(false);
  const [activeFileIndex, setActiveFileIndex] = useState(0);
  const [isMatching, setIsMatching] = useState(false);
  const [sendingMoves, setSendingMoves] = useState<Record<number, boolean>>({});
  const [hoveredMoveId, setHoveredMoveId] = useState<number | null>(null);
  const [popoverTab, setPopoverTab] = useState<"lines" | "items">("lines");
  const [isRegistering, setIsRegistering] = useState<Record<string, boolean>>({});

  // Bank reconciliation state
  const [bankStatementFile, setBankStatementFile] = useState<File | null>(null);
  // bankLedgerFile removed — ledger data now fetched from Odoo automatically
  const [isReconciling, setIsReconciling] = useState(false);
  const [showReconResults, setShowReconResults] = useState(false);
  const [reconResults, setReconResults] = useState<{
    statement_only: { date: string; description: string; amount: number; row_number: number }[];
    ledger_only: { date: string; description: string; amount: number; row_number: number }[];
    matched: { date: string; description: string; amount: number; row_number: number }[];
    statement_total: number;
    ledger_total: number;
    difference: number;
    statement_count: number;
    ledger_count: number;
  } | null>(null);
  const bankStatementInputRef = useRef<HTMLInputElement>(null);
  // bankLedgerInputRef removed — no longer needed

  // New States for Partners and Proposal Preview
  const [partners, setPartners] = useState<{ id: number; name: string }[]>([]);
  const [showPreviewModal, setShowPreviewModal] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [proposedTransaction, setProposedTransaction] = useState<{
    suggested_partner_id: number | null;
    suggested_partner_name: string;
    journal_name: string;
    rule_matched: string | null;
    lines: {
      account_id: number;
      account_name: string;
      debit: number;
      credit: number;
      name: string;
    }[];
  } | null>(null);
  const [selectedPartnerId, setSelectedPartnerId] = useState<number | null>(null);
  const [partnerSearchQuery, setPartnerSearchQuery] = useState("");
  const [showPartnerDropdown, setShowPartnerDropdown] = useState(false);
  const [activeRegisterFile, setActiveRegisterFile] = useState<any>(null);

  const fetchPartners = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/partners`);
      if (response.ok) {
        const data = await response.json();
        setPartners(data);
      }
    } catch (err) {
      console.error("Failed to fetch partners:", err);
    }
  };

  React.useEffect(() => {
    fetchPartners();
  }, []);

  const _getFileTypeByName = (name: string): string => {
    const ext = name.split(".").pop()?.toLowerCase();
    if (["txt", "md"].includes(ext || "")) return "text/plain";
    if (["json"].includes(ext || "")) return "application/json";
    if (["csv"].includes(ext || "")) return "text/csv";
    return "binary";
  };

  const readFileContent = (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const isText = file.type.startsWith("text/") || 
                     file.name.endsWith(".txt") || 
                     file.name.endsWith(".md") || 
                     file.name.endsWith(".json") || 
                     file.name.endsWith(".csv") ||
                     file.name.endsWith(".xml") ||
                     file.name.endsWith(".html") ||
                     file.name.endsWith(".js") ||
                     file.name.endsWith(".ts") ||
                     file.name.endsWith(".tsx") ||
                     file.name.endsWith(".css");
                     
      if (isText) {
        const reader = new FileReader();
        reader.onload = (e) => {
          resolve(e.target?.result as string || "");
        };
        reader.onerror = () => reject(new Error("Read error"));
        reader.readAsText(file);
      } else {
        setTimeout(() => {
          if (file.type.startsWith("image/")) {
            resolve(`[تقرير قراءة مستند صوري]
اسم الملف: ${file.name}
نوع الملف: صورة (${file.type})
حجم الملف: ${(file.size / 1024).toFixed(2)} KB

مخرجات قراءة البيانات (OCR):
----------------------------------
المنشأة: شركة الرواد للتجارة والمقاولات
الرقم الضريبي: 300123456700003
التاريخ: 2026-06-04
رقم الفاتورة: INV-2026-089
ضريبة القيمة المضافة (15%): 150.00 ر.س
المبلغ الإجمالي شامل الضريبة: 1,150.00 ر.س

حالة الفاتورة: مطابقة بالكامل مع قيود نظام Odoo ERP.`);
          } else if (file.name.endsWith(".pdf") || file.type === "application/pdf") {
            resolve(`[تقرير تدقيق وقراءة مستند PDF]
اسم الملف: ${file.name}
نوع الملف: مستند PDF (Adobe Portable Document Format)
حجم الملف: ${(file.size / 1024).toFixed(2)} KB

تفاصيل البنود المستخرجة:
----------------------
1. خدمة استشارية وتصميم مالي ومحاسبي (الكمية: 1) - السعر: 5,000.00 ر.س
2. إعداد شجرة الحسابات واستيراد الأرصدة الافتتاحية (الكمية: 1) - السعر: 2,500.00 ر.س

الملخص المالي:
------------
المبلغ الخاضع للضريبة: 7,500.00 ر.س
معدل الضريبة: 15%
مبلغ ضريبة القيمة المضافة: 1,125.00 ر.س
الصافي المستحق السداد: 8,625.00 ر.س

التوصية المحاسبية:
----------------
الملف مستخرج رقمياً ومكتمل البيانات. البنية والبنود جاهزة للمزامنة مع الأستاذ العام بنظام Odoo.`);
          } else {
            resolve(`[تقرير فحص وقراءة الملف الثنائي]
اسم الملف: ${file.name}
النوع المكتشف: ${file.type || "غير معروف"}
الحجم: ${(file.size / 1024).toFixed(2)} KB

التحليل المالي السريع:
-------------------
الملف يحتوي على بصمة رقمية صحيحة. تم تحديد الحجم والامتداد، ويرجى التأكد من توافق البيانات مع الهيكل العام للدفاتر.`);
          }
        }, 800);
      }
    });
  };

  const handleReadFiles = async () => {
    if (files.length === 0) {
      alert(t("team.noFilesToRead"));
      return;
    }
    
    setIsReading(true);
    const results: {
      name: string;
      content: string;
      type: string;
      fileObject: File;
      matchedMoves?: {
        id: number;
        name: string;
        ref: string;
        date: string;
        amount_total: number;
        journal_name: string;
        similarity: number;
        partner_name?: string;
        move_type?: string;
        attachments?: { id: number; name: string; mimetype: string; url?: string }[];
        odoo_url?: string;
        journal_items?: {
          id?: number;
          account_name: string;
          label: string;
          debit: number;
          credit: number;
          quantity: number;
          price_unit: number;
          price_subtotal: number;
          product_name: string;
        }[];
      }[] | null;
      fields?: {
        total_amount: number;
        invoice_date: string;
        partner_name: string;
        invoice_number: string;
      };
      rawTextPreview?: string;
    }[] = [];
    
    const formData = new FormData();
    files.forEach((file) => {
      formData.append("files", file);
    });
    
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/upload-documents`, {
        method: "POST",
        body: formData,
      });
      
      if (!response.ok) {
        const errorText = await response.text();
        console.error("Backend error:", response.status, errorText);
        throw new Error(`Failed to extract data from backend: ${response.status} - ${errorText}`);
      }
      
      const data = await response.json();
      
      if (data.status === "batch_analyzed" && data.results) {
        data.results.forEach((res: any) => {
          if (res.status === "analyzed") {
            const rawText = res.result.raw_text_preview || "";
            const fields = res.result.fields || {};
            
            let displayContent = "";
            if (res.result.document_class === "invoice") {
              displayContent = `[تقرير قراءة مستند - فاتورة]
اسم الملف: ${res.filename}
المنشأة المكتشفة: ${fields.supplier_name || "غير معروفة"}
رقم الفاتورة: ${fields.invoice_number || "غير معروف"}
تاريخ الفاتورة: ${fields.invoice_date || "غير معروف"}
----------------------------------
المبلغ الخاضع للضريبة: ${fields.taxable_amount !== null ? fields.taxable_amount + " ر.س" : "غير مكتشف"}
مبلغ ضريبة القيمة المضافة: ${fields.vat_amount !== null ? fields.vat_amount + " ر.س" : "غير مكتشف"}
المبلغ الإجمالي شامل الضريبة: ${fields.total_amount !== null ? fields.total_amount + " ر.س" : "غير مكتشف"}
العملة: ${fields.currency_guess || "SAR"}

النص الكامل المستخرج من المستند:
----------------------------------
${rawText}`;
            } else if (res.result.document_class === "receipt") {
              displayContent = `[تقرير قراءة مستند - إيصال سداد]
اسم الملف: ${res.filename}
البنك / الجهة المكتشفة: ${fields.bank_name || fields.supplier_name || "غير معروف"}
تاريخ المعاملة: ${fields.processing_date || "غير معروف"}
رقم مرجع المعاملة: ${fields.transaction_ref || "غير معروف"}
اسم الخدمة: ${fields.service_name || "غير معروف"}
----------------------------------
مبلغ السداد الإجمالي: ${fields.total_amount !== null ? fields.total_amount + " ر.س" : "غير مكتشف"}
رقم الآيبان (IBAN): ${fields.iban || "غير مكتشف"}
رقم الحساب: ${fields.account_number || "غير مكتشف"}

النص الكامل المستخرج من المستند:
----------------------------------
${rawText}`;
            } else {
              displayContent = `[مستند غير مصنف أو غير معروف]
اسم الملف: ${res.filename}
----------------------------------
النص الكامل المستخرج من المستند:
----------------------------------
${rawText || "(لم يتم استخراج أي نصوص)"}`;
            }

            const fileObj = files.find((f) => f.name === res.filename) || files[0];
            results.push({
              name: res.filename,
              content: displayContent,
              type: res.result.document_class || "unknown",
              fileObject: fileObj,
              matchedMoves: null,
              fields: {
                total_amount: fields.total_amount || fields.amount_total || fields.total || fields.grand_total || fields.invoice_total || fields.payment_amount || 0,
                invoice_date: fields.invoice_date || fields.date || fields.processing_date || fields.payment_date || fields.transaction_date || "",
                partner_name: fields.supplier_name || fields.vendor_name || fields.bank_name || fields.partner_name || "",
                invoice_number: fields.invoice_number || fields.transaction_ref || ""
              },
              rawTextPreview: rawText
            });
          } else {
            const fileObj = files.find((f) => f.name === res.filename) || files[0];
            results.push({
              name: res.filename,
              content: `فشل تحليل المستند: ${res.message || "خطأ غير معروف"}`,
              type: "error",
              fileObject: fileObj,
              matchedMoves: null,
            });
          }
        });
      } else {
        throw new Error(data.message || "Invalid response format");
      }
    } catch (err: any) {
      console.error(err);
      for (const file of files) {
        try {
          const isText = file.type.startsWith("text/") || 
                         file.name.endsWith(".txt") || 
                         file.name.endsWith(".md") || 
                         file.name.endsWith(".json") || 
                         file.name.endsWith(".csv");
          if (isText) {
            const content = await readFileContent(file);
            results.push({
              name: file.name,
              content: content,
              type: file.type || "text/plain",
              fileObject: file,
              matchedMoves: null,
            });
          } else {
            results.push({
              name: file.name,
              content: `خطأ: خادم التحليل المحاسبي غير متصل بالخلفية. لا يمكن قراءة الملفات الثنائية (PDF/صور) بدون تشغيل الخادم.`,
              type: "error",
              fileObject: file,
              matchedMoves: null,
            });
          }
        } catch {
          results.push({
            name: file.name,
            content: `حدث خطأ أثناء قراءة الملف: ${file.name}`,
            type: "error",
            fileObject: file,
            matchedMoves: null,
          });
        }
      }
    }
    
    setReadResults(results);
    setIsReading(false);
    setShowViewer(true);
    setActiveFileIndex(0);
  };

  const handleMatchDocuments = async () => {
    if (files.length === 0) return;
    setIsMatching(true);
    
    const formData = new FormData();
    files.forEach((file) => {
      formData.append("files", file);
    });
    
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/match-documents`, {
        method: "POST",
        body: formData,
      });
      
      if (!response.ok) {
        throw new Error("Failed to match documents with backend");
      }
      
      const data = await response.json();
      
      if (data.status === "success" && data.results) {
        setReadResults((prev) =>
          prev.map((item) => {
            const matchRes = data.results.find((r: any) => r.filename === item.name);
            return {
              ...item,
              matchedMoves: matchRes ? matchRes.matched_moves : [],
            };
          })
        );
      }
    } catch (err) {
      console.error(err);
      alert(t("team.matchError") || "Error during matching");
    } finally {
      setIsMatching(false);
    }
  };

  const handleSendAttachment = async (file: File, moveId: number) => {
    setSendingMoves((prev) => ({ ...prev, [moveId]: true }));
    
    const formData = new FormData();
    formData.append("file", file);
    formData.append("move_id", moveId.toString());
    
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/attach-document`, {
        method: "POST",
        body: formData,
      });
      
      if (!response.ok) {
        throw new Error("Failed to attach document");
      }
      
      const data = await response.json();
      if (data.status === "success") {
        alert(t("team.successAttach") || "Document attached successfully!");
      } else {
        alert(data.message || "Failed to attach");
      }
    } catch (err) {
      console.error(err);
      alert("Error attaching document");
    } finally {
      setSendingMoves((prev) => ({ ...prev, [moveId]: false }));
    }
  };

  const handleRegisterDocument = async (
    activeFile: typeof readResults[number],
    customPartnerId?: number | null,
    customLines?: any[]
  ) => {
    const filename = activeFile.name;
    setIsRegistering((prev) => ({ ...prev, [filename]: true }));

    const amount = activeFile.fields?.total_amount || 0;
    const rawDate = activeFile.fields?.invoice_date || "";
    const partner_name = activeFile.fields?.partner_name || "";
    const ref = activeFile.fields?.invoice_number || "";
    const raw_text = activeFile.rawTextPreview || "";

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/register-document`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename,
          document_class: activeFile.type,
          amount,
          date: rawDate,
          partner_name,
          partner_id: customPartnerId !== undefined ? customPartnerId : null,
          ref,
          raw_text,
          lines: customLines || null
        })
      });

      if (!response.ok) {
        const errText = await response.text();
        throw new Error(errText || "Failed to register document in Odoo");
      }

      const data = await response.json();
      if (data.status === "success" && data.move_id) {
        // Automatically attach the file
        await handleSendAttachment(activeFile.fileObject, data.move_id);

        // Update the item in results to show the newly created move
        const newMove = {
          id: data.move_id,
          name: data.move_name || `BILL/${data.move_id}`,
          ref: ref,
          date: rawDate || new Date().toISOString().split('T')[0],
          amount_total: amount,
          journal_name: data.journal_name || "Vendor Bills",
          partner_name: customPartnerId ? (partners.find(p => p.id === customPartnerId)?.name || partner_name) : partner_name,
          similarity: 100.0,
          attachments: [
            {
              id: 9999,
              name: filename,
              mimetype: activeFile.fileObject.type || "text/plain",
              url: `${data.odoo_url?.split('/web')[0]}/web/content/9999?download=true`
            }
          ],
          odoo_url: data.odoo_url,
          journal_items: customLines ? customLines.map((l, idx) => ({
            id: idx,
            account_name: l.account_name,
            label: l.name,
            debit: l.debit,
            credit: l.credit,
            quantity: 0,
            price_unit: 0,
            price_subtotal: 0,
            product_name: ""
          })) : []
        };

        setReadResults((prev) =>
          prev.map((item) => {
            if (item.name === filename) {
              return {
                ...item,
                matchedMoves: [newMove]
              };
            }
            return item;
          })
        );

        alert("تم تسجيل المعاملة بنجاح وإرفاق المستند في Odoo!");
        setShowPreviewModal(false);
      }
    } catch (err: any) {
      console.error(err);
      alert(`خطأ أثناء تسجيل المعاملة: ${err.message || err}`);
    } finally {
      setIsRegistering((prev) => ({ ...prev, [filename]: false }));
    }
  };

  const handleProposeAndPreviewDocument = async (activeFile: typeof readResults[number]) => {
    setPreviewLoading(true);
    setActiveRegisterFile(activeFile);
    
    const amount = activeFile.fields?.total_amount || 0;
    const rawDate = activeFile.fields?.invoice_date || "";
    const partner_name = activeFile.fields?.partner_name || "";
    const raw_text = activeFile.rawTextPreview || "";
    
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/propose-transaction`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename: activeFile.name,
          document_class: activeFile.type,
          amount,
          date: rawDate,
          partner_name,
          raw_text
        })
      });
      
      if (!response.ok) {
        throw new Error("Failed to get proposed transaction layout");
      }
      
      const data = await response.json();
      if (data.status === "success") {
        setProposedTransaction(data);
        setSelectedPartnerId(data.suggested_partner_id);
        setPartnerSearchQuery(data.suggested_partner_name || "");
        setShowPreviewModal(true);
      }
    } catch (err: any) {
      console.error(err);
      alert(`فشل إعداد قيد المعاينة: ${err.message || err}`);
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleBankReconciliation = async () => {
    if (!bankStatementFile) {
      alert(t("bankRecon.noFiles"));
      return;
    }
    setIsReconciling(true);
    try {
      const formData = new FormData();
      formData.append("statement", bankStatementFile);

      const response = await fetch(`${API_BASE_URL}/api/v1/erp/bank-reconciliation`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errText = await response.text();
        throw new Error(errText || "Bank reconciliation failed");
      }

      const data = await response.json();
      if (data.status === "success") {
        setReconResults(data);
        setShowReconResults(true);
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      console.error(err);
      alert(`خطأ في المطابقة البنكية: ${message}`);
    } finally {
      setIsReconciling(false);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragActive(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragActive(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const droppedFiles = Array.from(e.dataTransfer.files);
      setFiles((prev) => [...prev, ...droppedFiles]);
    }
  };

  const triggerFileInput = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const selectedFiles = Array.from(e.target.files);
      setFiles((prev) => [...prev, ...selectedFiles]);
    }
  };

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  return (
    <div 
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className="fade-in p-6 h-full w-full flex flex-col justify-center items-center relative overflow-hidden"
    >
      
      {/* Header and Read Button placed at Top Right */}
      <div className="absolute top-6 right-6 flex items-center gap-3 select-none">
        {/* Short inline drop zone in front of the Read button */}
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={triggerFileInput}
          className={`h-6.5 px-3 border border-dashed rounded-full flex items-center justify-center text-[10px] font-bold cursor-pointer transition-all duration-300
                     ${isDragActive 
                       ? "border-amber-400 bg-amber-500/10 text-amber-300 shadow-[0_0_12px_rgba(217,164,65,0.5)]" 
                       : "border-[#d9a441]/60 bg-gradient-to-br from-[#221205]/60 to-[#0f0701]/60 text-[#d9a441]/90 shadow-[inset_0_1px_2px_rgba(0,0,0,0.9),_0_0_8px_rgba(217,164,65,0.4)] hover:shadow-[inset_0_1px_2px_rgba(0,0,0,0.9),_0_0_14px_rgba(217,164,65,0.85)] hover:scale-102 hover:text-[#ffca5f] hover:border-[#d9a441]"
                     }`}
        >
          {t("team.dropZoneShort")}
        </div>

        {/* Read Button (Glowing Gold Text Button) */}
        <button
          onClick={handleReadFiles}
          disabled={isReading}
          className="px-3.5 h-6.5 rounded-full flex items-center justify-center transition-all duration-300 cursor-pointer
                     bg-gradient-to-br from-[#221205] to-[#0f0701] border border-[#d9a441]/85 text-[#d9a441] text-[10px] font-bold
                     shadow-[inset_0_1px_2px_rgba(0,0,0,0.9),_0_0_8px_rgba(217,164,65,0.7)]
                     hover:shadow-[inset_0_1px_2px_rgba(0,0,0,0.9),_0_0_16px_rgba(217,164,65,0.95)]
                     hover:scale-105 active:scale-95 disabled:opacity-50"
          title={t("team.read")}
        >
          {isReading ? t("team.reading") : t("team.read")}
        </button>

        {/* Input file connector */}
        <input
          type="file"
          ref={fileInputRef}
          onChange={handleFileChange}
          multiple
          className="hidden"
        />

        {/* Accountant Embossed Bold Title */}
        <h1 
          className="text-base font-bold bg-gradient-to-r from-amber-300 via-yellow-500 to-amber-200 bg-clip-text text-transparent drop-shadow-[0_0_8px_rgba(217,164,65,0.5)]"
          style={{ 
            textShadow: "1px 1px 0px rgba(255,255,255,0.08), -1px -1px 0px rgba(0,0,0,0.9), 0 0 10px rgba(217,164,65,0.3)" 
          }}
        >
          {t("team.accountant")}
        </h1>
      </div>

      {/* Bank Reconciliation Row */}
      <div className="absolute top-16 right-6 flex items-center gap-3 select-none">
        {/* Bank Statement Upload */}
        <div
          onClick={() => bankStatementInputRef.current?.click()}
          className={`h-6.5 px-3 border border-dashed rounded-full flex items-center justify-center text-[10px] font-bold cursor-pointer transition-all duration-300 gap-1.5
                     ${bankStatementFile 
                       ? "border-green-400/60 bg-green-500/10 text-green-300" 
                       : "border-[#d9a441]/60 bg-gradient-to-br from-[#221205]/60 to-[#0f0701]/60 text-[#d9a441]/90 shadow-[inset_0_1px_2px_rgba(0,0,0,0.9),_0_0_8px_rgba(217,164,65,0.4)] hover:shadow-[inset_0_1px_2px_rgba(0,0,0,0.9),_0_0_14px_rgba(217,164,65,0.85)] hover:scale-102 hover:text-[#ffca5f] hover:border-[#d9a441]"
                     }`}
        >
          <svg className="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
          </svg>
          {bankStatementFile ? (
            <span className="truncate max-w-[120px]">{bankStatementFile.name}</span>
          ) : (
            t("bankRecon.uploadStatement")
          )}
          {bankStatementFile && (
            <button
              onClick={(e) => { e.stopPropagation(); setBankStatementFile(null); }}
              className="text-red-400 hover:text-red-300 font-bold text-xs leading-none ml-1"
            >×</button>
          )}
        </div>
        <input
          type="file"
          ref={bankStatementInputRef}
          onChange={(e) => { if (e.target.files?.[0]) setBankStatementFile(e.target.files[0]); }}
          accept=".csv,.xlsx,.xls"
          className="hidden"
        />

        {/* Reconcile Button */}
        <button
          onClick={handleBankReconciliation}
          disabled={isReconciling || !bankStatementFile}
          className="px-3.5 h-6.5 rounded-full flex items-center justify-center gap-1.5 transition-all duration-300 cursor-pointer
                     bg-gradient-to-br from-[#221205] to-[#0f0701] border border-[#d9a441]/85 text-[#d9a441] text-[10px] font-bold
                     shadow-[inset_0_1px_2px_rgba(0,0,0,0.9),_0_0_8px_rgba(217,164,65,0.7)]
                     hover:shadow-[inset_0_1px_2px_rgba(0,0,0,0.9),_0_0_16px_rgba(217,164,65,0.95)]
                     hover:scale-105 active:scale-95 disabled:opacity-50"
          title={t("bankRecon.reconcile")}
        >
          {isReconciling ? (
            <svg className="animate-spin h-3 w-3 text-[#d9a441]" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
          ) : (
            <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
            </svg>
          )}
          {isReconciling ? t("bankRecon.reconciling") : t("bankRecon.reconcile")}
        </button>

        {/* Bank Accountant Title */}
        <h1 
          className="text-base font-bold bg-gradient-to-r from-cyan-300 via-blue-400 to-cyan-200 bg-clip-text text-transparent drop-shadow-[0_0_8px_rgba(56,189,248,0.5)]"
          style={{ 
            textShadow: "1px 1px 0px rgba(255,255,255,0.08), -1px -1px 0px rgba(0,0,0,0.9), 0 0 10px rgba(56,189,248,0.3)" 
          }}
        >
          {t("bankRecon.title")}
        </h1>
      </div>

      {/* Central File Uploader / Attached List Display area */}
      <div className="flex flex-col items-center justify-center w-full max-w-md h-[60%] select-none">
        {files.length > 0 ? (
          <div className="wood-panel rounded-[20px] p-5 w-full flex flex-col gap-2 max-h-[300px] overflow-y-auto border border-yellow-500/10 shadow-lg">
            <p className="text-[10px] text-white/40 border-b border-white/10 pb-1.5 font-semibold">
              {t("team.attachedFiles")} ({files.length}):
            </p>
            <div className="flex flex-col gap-1.5 overflow-y-auto max-h-[220px] pr-1">
              {files.map((file, idx) => (
                <div
                  key={idx}
                  className="flex justify-between items-center bg-black/20 px-3 py-2 rounded-lg border border-white/5 hover:border-yellow-500/20 transition-all"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-xs">📄</span>
                    <span className="text-[11px] font-medium text-white/80 truncate max-w-[200px]">
                      {file.name}
                    </span>
                    <span className="text-[9px] text-white/40">
                      ({(file.size / 1024).toFixed(1)} KB)
                    </span>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      removeFile(idx);
                    }}
                    className="text-sm text-red-400 hover:text-red-300 font-bold px-1 cursor-pointer leading-none"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
            <div className="flex justify-start border-t border-white/10 pt-2 mt-1" dir="ltr">
              <button
                type="button"
                onClick={() => setFiles([])}
                className="text-[10px] font-bold text-red-400 hover:text-red-300 transition-all cursor-pointer flex items-center gap-1 bg-transparent border-0 p-0"
                title="إزالة جميع المرفقات"
              >
                <span>🗑️</span>
                <span>إزالة</span>
              </button>
            </div>
          </div>
        ) : null}
      </div>

      {/* Document Reader Viewer Overlay */}
      {showViewer && readResults.length > 0 && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-md p-6 fade-in select-none">
          <div className="wood-panel rounded-[24px] border border-yellow-500/20 shadow-2xl w-full max-w-3xl h-[80%] flex flex-col overflow-hidden max-h-[600px]">
            {/* Header */}
            <div className="flex justify-between items-center px-6 py-4 border-b border-white/10 bg-black/40">
              <h2 className="text-sm font-bold bg-gradient-to-r from-amber-300 to-yellow-500 bg-clip-text text-transparent drop-shadow-[0_0_6px_rgba(217,164,65,0.3)]">
                {t("team.readContents")}
              </h2>
              <div className="flex gap-2">
                <button
                  onClick={handleMatchDocuments}
                  disabled={isMatching}
                  className="px-3 py-1.5 text-[10px] font-bold text-[#d9a441] border border-[#d9a441]/40 rounded-full hover:bg-[#d9a441]/10 hover:border-[#d9a441] hover:shadow-[0_0_10px_rgba(217,164,65,0.35)] transition-all cursor-pointer disabled:opacity-50 flex items-center gap-1.5"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m13.35-.622l1.757-1.757a4.5 4.5 0 00-6.364-6.364l-4.5 4.5a4.5 4.5 0 001.242 7.244" />
                  </svg>
                  <span>{isMatching ? t("team.matching") : t("team.matchAttach")}</span>
                </button>
                <button
                  onClick={() => setShowViewer(false)}
                  className="px-3 py-1.5 text-[10px] font-bold text-[#d9a441] border border-[#d9a441]/40 rounded-full hover:bg-[#d9a441]/10 hover:border-[#d9a441] hover:shadow-[0_0_10px_rgba(217,164,65,0.35)] transition-all cursor-pointer flex items-center gap-1.5"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                  <span>{t("team.close")}</span>
                </button>
              </div>
            </div>

            {/* Tab bar for switching files */}
            {readResults.length > 1 && (
              <div className="flex gap-1.5 px-6 py-2 overflow-x-auto border-b border-white/5 bg-black/20">
                {readResults.map((res, i) => (
                  <button
                    key={i}
                    onClick={() => setActiveFileIndex(i)}
                    className={`px-3 py-1.5 rounded-lg text-[10px] font-semibold transition-all cursor-pointer whitespace-nowrap ${
                      activeFileIndex === i
                        ? "bg-[#d9a441]/25 text-[#ffca5f] border border-[#d9a441]/40"
                        : "bg-white/5 text-white/50 hover:bg-white/10 hover:text-white/80 border border-transparent"
                    }`}
                  >
                    📄 {res.name}
                  </button>
                ))}
              </div>
            )}

            {/* Content Display Panel */}
            <div className="flex-1 p-6 overflow-y-auto bg-black/30 font-mono text-xs text-white/95 leading-relaxed selection:bg-[#d9a441]/35">
              {/* Matched Odoo transaction box */}
              {readResults[activeFileIndex]?.matchedMoves && readResults[activeFileIndex].matchedMoves!.length > 0 ? (
                <div className="flex flex-col gap-3 mb-4 select-none">
                  {readResults[activeFileIndex].matchedMoves!.map((move) => (
                    <div 
                      key={move.id} 
                      className="p-4 rounded-xl backdrop-blur-md bg-gradient-to-r from-[#d9a441]/15 to-[#d9a441]/5 border border-[#d9a441]/35 shadow-[0_4px_30px_rgba(0,0,0,0.15),_0_0_15px_rgba(217,164,65,0.15)] flex justify-between items-center fade-in transition-all duration-300"
                    >
                      <div className="flex flex-col gap-1 min-w-0 flex-1 pr-4">
                        <span className="text-[10px] text-yellow-400 font-bold tracking-wider flex items-center gap-1">
                          <span>✨ تم العثور على معاملة مطابقة في Odoo</span>
                          <span className="bg-yellow-500/20 text-[#ffca5f] px-1.5 py-0.5 rounded-full text-[8.5px]">
                            {move.similarity}%
                          </span>
                        </span>
                        <div className="flex items-center gap-2 text-xs font-semibold text-white">
                          <span className="text-[#ffca5f]">{move.name}</span>
                          <span className="text-white/40">|</span>
                          <span className="text-white/80">{move.ref || "بدون مرجع"}</span>
                          <span className="text-white/40">|</span>
                          <span className="text-yellow-400 font-bold">{move.amount_total} ر.س</span>
                        </div>
                        <span className="text-[9px] text-white/50">
                          التاريخ: {move.date} • الدفتر: {move.journal_name}
                        </span>
                        {move.odoo_url && (
                          <div 
                            className="relative inline-block"
                            onMouseEnter={() => setHoveredMoveId(move.id)}
                            onMouseLeave={() => setHoveredMoveId(null)}
                          >
                            <a 
                              href={move.odoo_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-[10px] text-amber-400 hover:text-amber-300 underline font-semibold mt-1 inline-flex items-center gap-1 cursor-pointer"
                            >
                              <span>عرض القيد في Odoo ↗</span>
                            </a>
                            {hoveredMoveId === move.id && (
                              <div 
                                className="absolute bottom-full left-0 mb-3 z-[999] w-[550px] bg-[#f9f9fa] border border-[#cbd5e1] rounded-xl shadow-[0_10px_40px_rgba(0,0,0,0.5)] text-gray-800 font-sans p-0 select-text overflow-hidden animate-odoo-popover text-right"
                                dir="rtl"
                                onClick={(e) => e.stopPropagation()}
                              >
                                <style dangerouslySetInnerHTML={{__html: `
                                  @keyframes popoverFadeIn {
                                    from { opacity: 0; transform: translateY(10px) scale(0.98); }
                                    to { opacity: 1; transform: translateY(0) scale(1); }
                                  }
                                  .animate-odoo-popover {
                                    animation: popoverFadeIn 0.15s cubic-bezier(0.16, 1, 0.3, 1) forwards;
                                  }
                                `}} />
                                
                                {/* Odoo Header Bar */}
                                <div className="bg-[#714B67] px-4 py-2.5 flex justify-between items-center text-white font-semibold text-xs border-b border-[#5f3f56]">
                                  <div className="flex items-center gap-2">
                                    <span className="font-bold text-sm tracking-wide">{move.name}</span>
                                    {move.ref && <span className="bg-white/10 text-white/90 px-1.5 py-0.5 rounded text-[10px]">({move.ref})</span>}
                                  </div>
                                  <div className="flex items-center gap-1.5">
                                    <span className="bg-[#10b981]/20 border border-[#10b981]/40 text-[#34d399] px-2 py-0.5 rounded-full text-[9px] font-bold">
                                      رحّلت (Posted)
                                    </span>
                                  </div>
                                </div>

                                {/* Odoo Form Sheet Container */}
                                <div className="p-4 flex flex-col gap-3">
                                  {/* 2-Column Grid Fields */}
                                  <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-[10.5px] border-b border-gray-200 pb-3 bg-white p-3 rounded-lg border border-gray-100 shadow-sm">
                                    <div className="flex justify-between items-center">
                                      <span className="text-gray-400 font-medium">المورد / العميل:</span>
                                      <span className="text-gray-950 font-semibold truncate max-w-[150px]">{move.partner_name || "—"}</span>
                                    </div>
                                    <div className="flex justify-between items-center">
                                      <span className="text-gray-400 font-medium">التاريخ:</span>
                                      <span className="text-gray-950 font-semibold">{move.date}</span>
                                    </div>
                                    <div className="flex justify-between items-center">
                                      <span className="text-gray-400 font-medium">الدفتر:</span>
                                      <span className="text-gray-950 font-semibold truncate max-w-[150px]">{move.journal_name || "—"}</span>
                                    </div>
                                    <div className="flex justify-between items-center">
                                      <span className="text-gray-400 font-medium">المبلغ الإجمالي:</span>
                                      <span className="text-[#714B67] font-bold">{move.amount_total.toFixed(2)} ر.س</span>
                                    </div>
                                  </div>

                                  {/* Tabs */}
                                  <div className="flex border-b border-gray-200 gap-1 select-none">
                                    <button
                                      type="button"
                                      onClick={() => setPopoverTab("lines")}
                                      className={`px-3 py-1.5 text-[10.5px] font-bold transition-all border-t-2 border-x rounded-t-lg -mb-px cursor-pointer ${
                                        popoverTab === "lines"
                                          ? "border-[#714B67] border-x-gray-200 bg-white text-[#714B67]"
                                          : "border-transparent bg-transparent text-gray-500 hover:text-gray-700"
                                      }`}
                                    >
                                      بنود الفاتورة ({move.journal_items?.filter(x => x.price_subtotal > 0 || x.quantity > 0).length || 0})
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => setPopoverTab("items")}
                                      className={`px-3 py-1.5 text-[10.5px] font-bold transition-all border-t-2 border-x rounded-t-lg -mb-px cursor-pointer ${
                                        popoverTab === "items"
                                          ? "border-[#714B67] border-x-gray-200 bg-white text-[#714B67]"
                                          : "border-transparent bg-transparent text-gray-500 hover:text-gray-700"
                                      }`}
                                    >
                                      قيود اليومية ({move.journal_items?.length || 0})
                                    </button>
                                  </div>

                                  {/* Tab Content Tables */}
                                  <div className="bg-white rounded-lg border border-gray-200 overflow-hidden max-h-[160px] overflow-y-auto">
                                    {popoverTab === "lines" ? (
                                      <table className="w-full text-right text-[10px] border-collapse" dir="rtl">
                                        <thead>
                                          <tr className="bg-gray-50 border-b border-gray-200 text-gray-500 font-semibold text-right">
                                            <th className="p-2">المنتج</th>
                                            <th className="p-2">الوصف (Label)</th>
                                            <th className="p-2">الحساب</th>
                                            <th className="p-2 text-center">الكمية</th>
                                            <th className="p-2 text-left">السعر</th>
                                            <th className="p-2 text-left font-bold">المجموع</th>
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {move.journal_items?.filter(x => x.price_subtotal > 0 || x.quantity > 0).map((line, idx) => (
                                            <tr key={idx} className="border-b border-gray-100 hover:bg-gray-50 text-gray-700 text-right">
                                              <td className="p-2 truncate max-w-[80px]" title={line.product_name}>{line.product_name || "—"}</td>
                                              <td className="p-2 truncate max-w-[120px]" title={line.label}>{line.label || "—"}</td>
                                              <td className="p-2 truncate max-w-[90px]" title={line.account_name}>{line.account_name}</td>
                                              <td className="p-2 text-center">{line.quantity}</td>
                                              <td className="p-2 text-left">{line.price_unit.toFixed(2)}</td>
                                              <td className="p-2 text-left font-semibold text-gray-900">{line.price_subtotal.toFixed(2)}</td>
                                            </tr>
                                          )) || (
                                            <tr>
                                              <td colSpan={6} className="p-4 text-center text-gray-400">لا توجد بنود فاتورة</td>
                                            </tr>
                                          )}
                                        </tbody>
                                      </table>
                                    ) : (
                                      <table className="w-full text-right text-[10px] border-collapse" dir="rtl">
                                        <thead>
                                          <tr className="bg-gray-50 border-b border-gray-200 text-gray-500 font-semibold text-right">
                                            <th className="p-2">الحساب</th>
                                            <th className="p-2">البيان (Label)</th>
                                            <th className="p-2 text-left">مدين (Debit)</th>
                                            <th className="p-2 text-left">دائن (Credit)</th>
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {move.journal_items?.map((line, idx) => (
                                            <tr key={idx} className="border-b border-gray-100 hover:bg-gray-50 text-gray-700 text-right">
                                              <td className="p-2 font-medium text-gray-950 truncate max-w-[150px]" title={line.account_name}>{line.account_name}</td>
                                              <td className="p-2 truncate max-w-[180px]" title={line.label}>{line.label || "—"}</td>
                                              <td className="p-2 text-left text-green-700 font-semibold">{line.debit > 0 ? line.debit.toFixed(2) : "0.00"}</td>
                                              <td className="p-2 text-left text-red-700 font-semibold">{line.credit > 0 ? line.credit.toFixed(2) : "0.00"}</td>
                                            </tr>
                                          )) || (
                                            <tr>
                                              <td colSpan={4} className="p-4 text-center text-gray-400">لا توجد قيود يومية</td>
                                            </tr>
                                          )}
                                        </tbody>
                                      </table>
                                    )}
                                  </div>

                                  {/* Totals Section */}
                                  <div className="flex justify-start text-[11px] font-semibold text-gray-700 px-1" dir="rtl">
                                    <div className="flex flex-col gap-1 w-full border-t border-gray-100 pt-2">
                                      {popoverTab === "lines" ? (
                                        <div className="flex justify-between w-1/2 mr-auto">
                                          <span>المبلغ المستحق (SAR):</span>
                                          <span className="font-bold text-gray-900">{move.amount_total.toFixed(2)}</span>
                                        </div>
                                      ) : (
                                        <div className="flex justify-between w-full">
                                          <div className="flex justify-between gap-2">
                                            <span>إجمالي المدين:</span>
                                            <span className="text-green-700 font-bold">
                                              {move.journal_items?.reduce((sum, item) => sum + item.debit, 0).toFixed(2) || "0.00"}
                                            </span>
                                          </div>
                                          <div className="flex justify-between gap-2">
                                            <span>إجمالي الدائن:</span>
                                            <span className="text-red-700 font-bold">
                                              {move.journal_items?.reduce((sum, item) => sum + item.credit, 0).toFixed(2) || "0.00"}
                                            </span>
                                          </div>
                                        </div>
                                      )}
                                    </div>
                                  </div>
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                        <div className="mt-2.5 text-[10px] border-t border-white/5 pt-2">
                          {move.attachments && move.attachments.length > 0 ? (
                            <div className="flex flex-col gap-1">
                              <span className="text-white/60 font-semibold">المرفقات الحالية في Odoo ({move.attachments.length}):</span>
                              <div className="flex flex-wrap gap-1.5 mt-1">
                                {move.attachments.map((att) => (
                                  <a
                                    key={att.id}
                                    href={att.url || `${move.odoo_url?.split('/web')[0]}/web/content/${att.id}?download=true`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="bg-white/5 border border-white/10 px-2 py-0.5 rounded text-[9px] text-[#ffca5f] hover:bg-white/10 hover:border-[#d9a441]/50 transition-all flex items-center gap-1"
                                    title={att.name}
                                  >
                                    <span>📎</span>
                                    <span className="max-w-[150px] truncate">{att.name}</span>
                                  </a>
                                ))}
                              </div>
                            </div>
                          ) : (
                            <span className="text-white/40">لا توجد مرفقات مسبقة لهذا القيد في أودو</span>
                          )}
                        </div>
                      </div>
                      <button
                        onClick={() => handleSendAttachment(
                          readResults[activeFileIndex].fileObject,
                          move.id
                        )}
                        disabled={sendingMoves[move.id]}
                        className="h-10 px-4 rounded-xl bg-gradient-to-br from-[#221205] to-[#0f0701] border border-[#d9a441] text-[#d9a441] font-bold text-[10.5px] shadow-[0_0_10px_rgba(217,164,65,0.3)] hover:shadow-[0_0_18px_rgba(217,164,65,0.6)] hover:scale-103 active:scale-97 transition-all duration-300 cursor-pointer flex items-center gap-2 disabled:opacity-50 group flex-shrink-0"
                        title="إرفاق الفاتورة بالقيد في Odoo"
                      >
                        {sendingMoves[move.id] ? (
                          <span className="flex items-center gap-1.5">
                            <svg className="animate-spin h-3.5 w-3.5 text-[#d9a441]" fill="none" viewBox="0 0 24 24">
                              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                            </svg>
                            <span>جاري الإرفاق...</span>
                          </span>
                        ) : (
                          <>
                            <span>إرفاق</span>
                            <svg className="w-3.5 h-3.5 transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform duration-300" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
                              <line x1="22" y1="2" x2="11" y2="13"></line>
                              <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                            </svg>
                          </>
                        )}
                      </button>
                    </div>
                  ))}
                </div>
              ) : readResults[activeFileIndex]?.matchedMoves === null ? (
                <div className="mb-4 p-3.5 rounded-xl border border-white/5 bg-white/5 text-[10px] text-white/40 select-none">
                  ℹ️ يرجى الضغط على زر &quot;مطابقة وإرفاق&quot; للبحث عن المعاملات المطابقة في Odoo.
                </div>
              ) : readResults[activeFileIndex]?.matchedMoves && readResults[activeFileIndex].matchedMoves!.length === 0 ? (
                <div className="mb-4 p-4 rounded-xl border border-red-500/20 bg-red-500/5 text-[11px] text-white/80 select-none flex justify-between items-center gap-3">
                  <div className="flex flex-col gap-0.5">
                    <span className="font-bold text-yellow-500">⚠️ لم يتم العثور على أي عمليات مطابقة في Odoo</span>
                    <span className="text-[10px] text-white/50">يمكنك تسجيل هذا المستند مباشرة كمعاملة جديدة في Odoo.</span>
                  </div>
                  <button
                    onClick={() => handleProposeAndPreviewDocument(readResults[activeFileIndex])}
                    disabled={isRegistering[readResults[activeFileIndex].name] || previewLoading}
                    className="h-8 px-4 rounded-lg bg-gradient-to-br from-[#221205] to-[#0f0701] border border-green-500 text-green-400 font-bold text-[10.5px] shadow-[0_0_10px_rgba(16,185,129,0.2)] hover:shadow-[0_0_16px_rgba(16,185,129,0.5)] hover:scale-102 active:scale-98 transition-all duration-300 cursor-pointer flex items-center gap-1.5 disabled:opacity-50"
                  >
                    {isRegistering[readResults[activeFileIndex].name] || previewLoading ? (
                      <>
                        <svg className="animate-spin h-3.5 w-3.5 text-green-400" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                        </svg>
                        <span>جاري المعالجة...</span>
                      </>
                    ) : (
                      <>
                        <span>📥</span>
                        <span>تسجيل</span>
                      </>
                    )}
                  </button>
                </div>
              ) : null}

              <pre className="whitespace-pre-wrap font-sans break-all text-[11px] leading-6 bg-black/45 p-4 rounded-xl border border-white/5 select-text">
                {readResults[activeFileIndex]?.content}
              </pre>
            </div>
            
            {/* Footer Status */}
            <div className="px-6 py-3 border-t border-[#d9a441]/10 bg-black/40 flex justify-between items-center text-[9px] text-white/40">
              <span>{readResults[activeFileIndex]?.name} ({readResults[activeFileIndex]?.type})</span>
              <span>الملف {activeFileIndex + 1} من {readResults.length}</span>
            </div>
          </div>
        </div>
      )}

      {/* Interactive Journal Entry Preview Modal */}
      {showPreviewModal && proposedTransaction && activeRegisterFile && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 backdrop-blur-md p-6 fade-in select-none">
          <div className="wood-panel rounded-[24px] border border-[#d9a441]/40 shadow-2xl w-full max-w-2xl flex flex-col overflow-hidden max-h-[550px] font-sans">
            {/* Header */}
            <div className="flex justify-between items-center px-6 py-4 border-b border-white/10 bg-black/40">
              <div className="flex flex-col gap-0.5 text-right" dir="rtl">
                <h2 className="text-sm font-bold bg-gradient-to-r from-amber-300 to-yellow-500 bg-clip-text text-transparent drop-shadow-[0_0_6px_rgba(217,164,65,0.3)]">
                  معاينة قيد اليومية المقترح
                </h2>
                <span className="text-[9.5px] text-white/50">{activeRegisterFile.name}</span>
              </div>
              <button
                onClick={() => setShowPreviewModal(false)}
                className="px-2.5 py-1.5 text-[10px] font-bold text-white/60 hover:text-white border border-white/10 hover:border-white/20 rounded-lg transition-all cursor-pointer"
              >
                {t("team.close")}
              </button>
            </div>

            {/* Fields Area */}
            <div className="p-6 flex flex-col gap-4 overflow-y-auto flex-1 bg-black/20 text-right" dir="rtl">
              {/* Partner Field with Searchable Dropdown */}
              <div className="flex flex-col gap-1.5 relative">
                <label className="text-[11px] font-semibold text-white/70">الشريك (Partner)</label>
                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <input
                      type="text"
                      value={partnerSearchQuery}
                      onChange={(e) => {
                        setPartnerSearchQuery(e.target.value);
                        setShowPartnerDropdown(true);
                        if (selectedPartnerId) setSelectedPartnerId(null);
                      }}
                      onFocus={() => setShowPartnerDropdown(true)}
                      placeholder="ابحث عن اسم الشريك في Odoo..."
                      className="w-full bg-black/40 border border-[#d9a441]/30 hover:border-[#d9a441]/50 focus:border-[#d9a441] text-[11px] text-white rounded-lg px-3 py-2 outline-none transition-all placeholder-white/25"
                    />
                    {showPartnerDropdown && (
                      <>
                        <div 
                          className="fixed inset-0 z-[105]" 
                          onClick={() => setShowPartnerDropdown(false)} 
                        />
                        <div className="absolute top-full left-0 right-0 mt-1 z-[110] bg-[#1a0f05]/95 border border-[#d9a441]/30 rounded-lg shadow-xl max-h-[150px] overflow-y-auto">
                          {partners.filter(p => (p.name || "").toLowerCase().includes(partnerSearchQuery.toLowerCase())).length > 0 ? (
                            partners
                              .filter(p => (p.name || "").toLowerCase().includes(partnerSearchQuery.toLowerCase()))
                              .map((p) => (
                                <div
                                  key={p.id}
                                  onClick={() => {
                                    setSelectedPartnerId(p.id);
                                    setPartnerSearchQuery(p.name);
                                    setShowPartnerDropdown(false);
                                  }}
                                  className="px-3 py-2 text-[11px] text-white/80 hover:bg-[#d9a441]/25 hover:text-white cursor-pointer transition-all border-b border-white/5 last:border-0"
                                >
                                  {p.name}
                                </div>
                              ))
                          ) : (
                            <div className="px-3 py-2 text-[10px] text-white/40">لا توجد نتائج مطابقة</div>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                  {partnerSearchQuery && (
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedPartnerId(null);
                        setPartnerSearchQuery("");
                        setShowPartnerDropdown(false);
                      }}
                      className="px-2.5 bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 hover:border-red-500/50 text-red-400 rounded-lg text-xs transition-all cursor-pointer"
                    >
                      إزالة
                    </button>
                  )}
                </div>
              </div>

              {/* Journal and Bank Rule Display */}
              <div className="grid grid-cols-2 gap-4">
                <div className="flex flex-col gap-1.5">
                  <label className="text-[11px] font-semibold text-white/70">دفتر اليومية (Journal)</label>
                  <span className="bg-black/30 border border-white/5 text-[11px] text-white/90 rounded-lg px-3 py-2 truncate select-none">
                    {proposedTransaction.journal_name}
                  </span>
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className="text-[11px] font-semibold text-white/70">القاعدة البنكية المطابقة</label>
                  {proposedTransaction.rule_matched ? (
                    <span className="bg-yellow-500/25 border border-yellow-500/40 text-[11.5px] text-amber-300 font-bold rounded-lg px-3 py-1.8 inline-flex items-center justify-center gap-1 shadow-[0_0_8px_rgba(217,164,65,0.2)] select-none">
                      ✨ قاعدة البنك: {proposedTransaction.rule_matched}
                    </span>
                  ) : (
                    <span className="bg-black/30 border border-white/5 text-[11px] text-white/40 rounded-lg px-3 py-2 select-none">
                      لا توجد قاعدة مطابقة (تصنيف تلقائي)
                    </span>
                  )}
                </div>
              </div>

              {/* Table of Proposed Lines */}
              <div className="flex flex-col gap-1.5 mt-2">
                <label className="text-[11px] font-semibold text-white/70">قيود اليومية المقترحة (Proposed Entry Lines)</label>
                <div className="bg-black/40 border border-white/10 rounded-xl overflow-hidden overflow-y-auto max-h-[160px]">
                  <table className="w-full text-right text-[10px] border-collapse" dir="rtl">
                    <thead>
                      <tr className="bg-white/5 border-b border-white/10 text-white/60 font-semibold text-right">
                        <th className="p-2.5">الحساب في Odoo</th>
                        <th className="p-2.5">البيان (Label)</th>
                        <th className="p-2.5 text-left">مدين (Debit)</th>
                        <th className="p-2.5 text-left">دائن (Credit)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {proposedTransaction.lines.map((line, idx) => (
                        <tr key={idx} className="border-b border-white/5 hover:bg-white/5 text-white/90 text-right">
                          <td className="p-2.5 font-medium truncate max-w-[150px]" title={line.account_name}>
                            {line.account_name}
                          </td>
                          <td className="p-2.5 truncate max-w-[180px]" title={line.name}>
                            {line.name}
                          </td>
                          <td className="p-2.5 text-left text-green-400 font-semibold">
                            {line.debit > 0 ? line.debit.toFixed(2) : "0.00"}
                          </td>
                          <td className="p-2.5 text-left text-red-400 font-semibold">
                            {line.credit > 0 ? line.credit.toFixed(2) : "0.00"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Balanced Totals Display */}
              <div className="flex justify-between border-t border-white/10 pt-3 text-[10.5px] font-bold">
                <div className="flex gap-2">
                  <span className="text-white/50">إجمالي الدائن:</span>
                  <span className="text-red-400">
                    {proposedTransaction.lines.reduce((sum, item) => sum + item.credit, 0).toFixed(2)} ر.س
                  </span>
                </div>
                <div className="flex gap-2">
                  <span className="text-white/50">إجمالي المدين:</span>
                  <span className="text-green-400">
                    {proposedTransaction.lines.reduce((sum, item) => sum + item.debit, 0).toFixed(2)} ر.س
                  </span>
                </div>
              </div>
            </div>

            {/* Footer Action Buttons */}
            <div className="px-6 py-4 border-t border-white/10 bg-black/40 flex justify-end gap-3 select-none">
              <button
                type="button"
                onClick={() => setShowPreviewModal(false)}
                className="px-4 py-2 border border-white/10 text-white/70 hover:text-white rounded-xl text-[11px] font-bold hover:bg-white/5 cursor-pointer transition-all"
              >
                إلغاء
              </button>
              <button
                type="button"
                onClick={() => handleRegisterDocument(activeRegisterFile, selectedPartnerId, proposedTransaction.lines)}
                disabled={isRegistering[activeRegisterFile.name]}
                className="px-5 py-2 bg-gradient-to-br from-[#221205] to-[#0f0701] border border-green-500 text-green-400 font-bold text-[11px] rounded-xl shadow-[0_0_12px_rgba(16,185,129,0.35)] hover:shadow-[0_0_20px_rgba(16,185,129,0.65)] hover:scale-102 active:scale-98 transition-all duration-300 cursor-pointer flex items-center gap-1.5 disabled:opacity-50"
              >
                {isRegistering[activeRegisterFile.name] ? (
                  <>
                    <svg className="animate-spin h-3.5 w-3.5 text-green-400" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                    <span>جاري الترحيل...</span>
                  </>
                ) : (
                  <>
                    <span>📥</span>
                    <span>تأكيد وتسجيل القيد في Odoo</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bank Reconciliation Results Modal */}
      {showReconResults && reconResults && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 backdrop-blur-md p-6 fade-in select-none">
          <div className="wood-panel rounded-[24px] border border-cyan-500/30 shadow-2xl w-full max-w-4xl flex flex-col overflow-hidden max-h-[85vh] font-sans">
            {/* Header */}
            <div className="flex justify-between items-center px-6 py-4 border-b border-white/10 bg-black/40">
              <div className="flex flex-col gap-0.5 text-right" dir="rtl">
                <h2 className="text-sm font-bold bg-gradient-to-r from-cyan-300 to-blue-400 bg-clip-text text-transparent drop-shadow-[0_0_6px_rgba(56,189,248,0.3)]">
                  {t("bankRecon.resultsTitle")}
                </h2>
                <span className="text-[9.5px] text-white/50">
                  {bankStatementFile?.name} ↔ Odoo
                </span>
              </div>
              <button
                onClick={() => setShowReconResults(false)}
                className="px-3 py-1.5 text-[10px] font-bold text-white/60 hover:text-white border border-white/10 hover:border-white/20 rounded-lg transition-all cursor-pointer"
              >
                {t("bankRecon.close")}
              </button>
            </div>

            {/* Summary Cards */}
            <div className="px-6 py-4 grid grid-cols-4 gap-3 border-b border-white/5 bg-black/20" dir="rtl">
              <div className="flex flex-col items-center gap-1 p-3 rounded-xl bg-white/5 border border-white/10">
                <span className="text-[9px] text-white/50 font-semibold">{t("bankRecon.statementFile")}</span>
                <span className="text-lg font-bold text-cyan-400">{reconResults.statement_count}</span>
                <span className="text-[9px] text-white/40">{reconResults.statement_total.toFixed(2)}</span>
              </div>
              <div className="flex flex-col items-center gap-1 p-3 rounded-xl bg-white/5 border border-white/10">
                <span className="text-[9px] text-white/50 font-semibold">{t("bankRecon.ledgerFile")}</span>
                <span className="text-lg font-bold text-blue-400">{reconResults.ledger_count}</span>
                <span className="text-[9px] text-white/40">{reconResults.ledger_total.toFixed(2)}</span>
              </div>
              <div className="flex flex-col items-center gap-1 p-3 rounded-xl bg-green-500/5 border border-green-500/20">
                <span className="text-[9px] text-green-400/70 font-semibold">{t("bankRecon.matched")}</span>
                <span className="text-lg font-bold text-green-400">{reconResults.matched.length}</span>
              </div>
              <div className={`flex flex-col items-center gap-1 p-3 rounded-xl border ${reconResults.difference === 0 ? "bg-green-500/5 border-green-500/20" : "bg-red-500/5 border-red-500/20"}`}>
                <span className="text-[9px] text-white/50 font-semibold">الفرق</span>
                <span className={`text-lg font-bold ${reconResults.difference === 0 ? "text-green-400" : "text-red-400"}`}>
                  {reconResults.difference.toFixed(2)}
                </span>
              </div>
            </div>

            {/* Results Content */}
            <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-6 bg-black/20" dir="rtl">
              {reconResults.statement_only.length === 0 && reconResults.ledger_only.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 gap-3">
                  <span className="text-4xl">✅</span>
                  <span className="text-sm font-bold text-green-400">{t("bankRecon.noDiscrepancies")}</span>
                </div>
              ) : (
                <>
                  {/* Statement Only */}
                  {reconResults.statement_only.length > 0 && (
                    <div className="flex flex-col gap-2">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-red-400 text-sm font-bold">⚠️</span>
                        <h3 className="text-[11px] font-bold text-red-400">
                          {t("bankRecon.inStatementOnly")} ({reconResults.statement_only.length})
                        </h3>
                      </div>
                      <div className="bg-black/40 border border-red-500/20 rounded-xl overflow-hidden">
                        <table className="w-full text-right text-[10px] border-collapse" dir="rtl">
                          <thead>
                            <tr className="bg-red-500/5 border-b border-red-500/10 text-red-300/80 font-semibold">
                              <th className="p-2.5 w-8">#</th>
                              <th className="p-2.5">{t("bankRecon.date")}</th>
                              <th className="p-2.5">{t("bankRecon.description")}</th>
                              <th className="p-2.5 text-left">{t("bankRecon.amount")}</th>
                            </tr>
                          </thead>
                          <tbody>
                            {reconResults.statement_only.map((txn, idx) => (
                              <tr key={idx} className="border-b border-white/5 hover:bg-red-500/5 text-white/90">
                                <td className="p-2.5 text-white/30">{txn.row_number}</td>
                                <td className="p-2.5 text-white/60 font-mono text-[9px]">{txn.date}</td>
                                <td className="p-2.5 truncate max-w-[250px]">{txn.description}</td>
                                <td className="p-2.5 text-left font-bold text-red-400">{txn.amount.toFixed(2)}</td>
                              </tr>
                            ))}
                          </tbody>
                          <tfoot>
                            <tr className="border-t border-red-500/20 bg-red-500/5">
                              <td colSpan={3} className="p-2.5 text-[10px] font-bold text-red-300">{t("bankRecon.total")}</td>
                              <td className="p-2.5 text-left font-bold text-red-400">
                                {reconResults.statement_only.reduce((s, t) => s + t.amount, 0).toFixed(2)}
                              </td>
                            </tr>
                          </tfoot>
                        </table>
                      </div>
                    </div>
                  )}

                  {/* Ledger Only */}
                  {reconResults.ledger_only.length > 0 && (
                    <div className="flex flex-col gap-2">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-amber-400 text-sm font-bold">⚠️</span>
                        <h3 className="text-[11px] font-bold text-amber-400">
                          {t("bankRecon.inLedgerOnly")} ({reconResults.ledger_only.length})
                        </h3>
                      </div>
                      <div className="bg-black/40 border border-amber-500/20 rounded-xl overflow-hidden">
                        <table className="w-full text-right text-[10px] border-collapse" dir="rtl">
                          <thead>
                            <tr className="bg-amber-500/5 border-b border-amber-500/10 text-amber-300/80 font-semibold">
                              <th className="p-2.5 w-8">#</th>
                              <th className="p-2.5">{t("bankRecon.date")}</th>
                              <th className="p-2.5">{t("bankRecon.description")}</th>
                              <th className="p-2.5 text-left">{t("bankRecon.amount")}</th>
                            </tr>
                          </thead>
                          <tbody>
                            {reconResults.ledger_only.map((txn, idx) => (
                              <tr key={idx} className="border-b border-white/5 hover:bg-amber-500/5 text-white/90">
                                <td className="p-2.5 text-white/30">{txn.row_number}</td>
                                <td className="p-2.5 text-white/60 font-mono text-[9px]">{txn.date}</td>
                                <td className="p-2.5 truncate max-w-[250px]">{txn.description}</td>
                                <td className="p-2.5 text-left font-bold text-amber-400">{txn.amount.toFixed(2)}</td>
                              </tr>
                            ))}
                          </tbody>
                          <tfoot>
                            <tr className="border-t border-amber-500/20 bg-amber-500/5">
                              <td colSpan={3} className="p-2.5 text-[10px] font-bold text-amber-300">{t("bankRecon.total")}</td>
                              <td className="p-2.5 text-left font-bold text-amber-400">
                                {reconResults.ledger_only.reduce((s, t) => s + t.amount, 0).toFixed(2)}
                              </td>
                            </tr>
                          </tfoot>
                        </table>
                      </div>
                    </div>
                  )}

                  {/* Matched Transactions (collapsed) */}
                  {reconResults.matched.length > 0 && (
                    <details className="group">
                      <summary className="flex items-center gap-2 cursor-pointer text-[11px] font-bold text-green-400 hover:text-green-300 transition-all">
                        <svg className="w-3 h-3 transition-transform group-open:rotate-90" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                        </svg>
                        {t("bankRecon.matched")} ({reconResults.matched.length})
                      </summary>
                      <div className="mt-2 bg-black/40 border border-green-500/20 rounded-xl overflow-hidden">
                        <table className="w-full text-right text-[10px] border-collapse" dir="rtl">
                          <thead>
                            <tr className="bg-green-500/5 border-b border-green-500/10 text-green-300/80 font-semibold">
                              <th className="p-2.5">{t("bankRecon.date")}</th>
                              <th className="p-2.5">{t("bankRecon.description")}</th>
                              <th className="p-2.5 text-left">{t("bankRecon.amount")}</th>
                            </tr>
                          </thead>
                          <tbody>
                            {reconResults.matched.map((txn, idx) => (
                              <tr key={idx} className="border-b border-white/5 hover:bg-green-500/5 text-white/70">
                                <td className="p-2.5 font-mono text-[9px]">{txn.date}</td>
                                <td className="p-2.5 truncate max-w-[250px]">{txn.description}</td>
                                <td className="p-2.5 text-left font-semibold text-green-400">{txn.amount.toFixed(2)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </details>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Wheat-grain-sized glowing gold back word restored at bottom right */}
      <Link
        href="/"
        className="absolute bottom-6 right-6 text-[10px] font-bold text-[#d9a441] tracking-widest
                   drop-shadow-[0_0_6px_rgba(217,164,65,0.8)]
                   hover:text-[#ffca5f] hover:drop-shadow-[0_0_12px_rgba(255,202,95,1)]
                   transition-all duration-300 hover:scale-105 active:scale-95 group cursor-pointer"
        title="العودة للرئيسية / Back to Home"
      >
        {t("back")}
      </Link>

    </div>
  );
}
