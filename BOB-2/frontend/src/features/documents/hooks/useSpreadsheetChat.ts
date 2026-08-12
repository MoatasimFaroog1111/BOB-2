import React, { useEffect, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import { documentsGateway } from "@/features/documents/api/documentsGateway";
import { shouldParseAsBankStatement } from "@/features/documents/lib/bankStatementImport";
import {
  buildDailyBankReviewWorksheets,
  type DailyBankReviewDraft,
  type DailyBankReviewEntry,
} from "@/features/documents/lib/dailyBankReview";
import {
  createEmptyGrid,
  DEFAULT_WORKSHEET_COLUMNS,
  DEFAULT_WORKSHEET_ROWS,
} from "@/features/documents/hooks/useWorksheets";
import type { OdooJournal, Worksheet } from "@/features/documents/model/types";

interface SpreadsheetChatOptions {
  language: string;
  sheets: Worksheet[];
  setSheets: Dispatch<SetStateAction<Worksheet[]>>;
  activeSheetId: string;
  setActiveSheetId: Dispatch<SetStateAction<string>>;
  journals: OdooJournal[];
  selectedJournalId: number | null;
}

export function useSpreadsheetChat({
  language,
  sheets,
  setSheets,
  activeSheetId,
  setActiveSheetId,
  journals,
  selectedJournalId,
}: SpreadsheetChatOptions) {
  const [isUploading, setIsUploading] = useState(false);
  const [isSubmittingReview, setIsSubmittingReview] = useState(false);
  const [bankReviewDraft, setBankReviewDraft] = useState<DailyBankReviewDraft | null>(null);

  const chatMessagesEndRef = useRef<HTMLDivElement>(null);
  const chatFileInputRef = useRef<HTMLInputElement>(null);

  const [chatMessages, setChatMessages] = useState<{ role: "user" | "assistant"; text: string }[]>(() => [
    {
      role: "assistant",
      text: language === "ar"
        ? "مرحباً بك! أنا مساعد تنظيم وتنسيق الجداول المحاسبية. اكتب لي ما تريده من تعديلات أو تنسيق (مثال: 'نظم كقيد رواتب') وسأقوم بتعديل الشبكة لك."
        : "Hello! I am your spreadsheet layout assistant. Tell me what formatting or layout you want (e.g. 'format as payroll entry') and I will modify the grid for you."
    }
  ]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);

  useEffect(() => {
    if (chatMessagesEndRef.current) {
      chatMessagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [chatMessages]);

  const handleSendChatMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!chatInput.trim() || chatLoading) return;

    const userMsg = chatInput.trim();
    setChatInput("");
    setChatMessages((prev) => [...prev, { role: "user", text: userMsg }]);
    setChatLoading(true);

    try {
      const res = await documentsGateway.chatSpreadsheet({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: userMsg,
          sheets: sheets.map((sheet) => ({
            id: sheet.id,
            name: sheet.name,
            gridData: sheet.gridData,
            rowCount: sheet.rowCount,
            colCount: sheet.colCount,
          })),
          active_sheet_id: activeSheetId,
        }),
      });

      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();

      if (data.message) {
        setChatMessages((prev) => [...prev, { role: "assistant", text: data.message }]);
      }

      setSheets((prevSheets) => {
        let updated = [...prevSheets];

        if (data.grid_data && Array.isArray(data.grid_data)) {
          updated = updated.map((sheet) => {
            if (sheet.id !== activeSheetId) return sheet;
            const newGrid = data.grid_data;
            return {
              ...sheet,
              gridData: newGrid,
              rowCount: newGrid.length,
              colCount: newGrid[0]?.length || 0,
            };
          });
        }

        if (data.active_sheet_name) {
          updated = updated.map((sheet) =>
            sheet.id === activeSheetId ? { ...sheet, name: data.active_sheet_name } : sheet
          );
        }

        if (data.create_sheet && data.create_sheet.name) {
          const newId = `sheet-${Date.now()}`;
          const newGrid = data.create_sheet.grid_data || createEmptyGrid();
          updated.push({
            id: newId,
            name: data.create_sheet.name,
            gridData: newGrid,
            rowCount: newGrid.length,
            colCount: newGrid[0]?.length || 0,
          });
          setTimeout(() => setActiveSheetId(newId), 50);
        }

        if (data.delete_sheet_id && updated.length > 1) {
          const idToDelete = data.delete_sheet_id;
          updated = updated.filter((sheet) => sheet.id !== idToDelete);
          if (activeSheetId === idToDelete) {
            setActiveSheetId(updated[updated.length - 1].id);
          }
        }

        return updated;
      });
    } catch (err: any) {
      console.error(err);
      setChatMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: language === "ar"
            ? `عذراً، فشل الاتصال بالمساعد: ${err.message || err}`
            : `Sorry, failed to connect to the assistant: ${err.message || err}`,
        },
      ]);
    } finally {
      setChatLoading(false);
    }
  };

  const submitBankReview = async () => {
    if (!bankReviewDraft || isSubmittingReview) return null;
    setIsSubmittingReview(true);
    try {
      const response = await documentsGateway.submitDailyBankReview({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: bankReviewDraft.documentId,
          journal_id: bankReviewDraft.journalId,
          company_id: bankReviewDraft.companyId || null,
        }),
      });
      if (!response.ok) throw new Error(await response.text());
      const result = await response.json();
      const reviewIds = Array.isArray(result.reviews)
        ? result.reviews.map((item: any) => Number(item.approval_id)).filter(Number.isFinite)
        : [];
      setBankReviewDraft((current) => current ? { ...current, submitted: true, reviewIds } : current);
      setChatMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: language === "ar"
            ? `✅ تم إرسال ${Number(result.review_count || reviewIds.length).toLocaleString()} قيد يومي إلى المدقق الذكي. لم يتم ترحيل أي قيد إلى Odoo. افتح «المدقق الذكي» لتشغيل التدقيق ومراجعة الأدلة قبل الاعتماد.`
            : `✅ ${Number(result.review_count || reviewIds.length).toLocaleString()} daily journal entries were sent to Smart Auditor. Nothing was posted to Odoo. Open Smart Auditor to run the audit and review the evidence before approval.`,
        },
      ]);
      return result;
    } catch (err: any) {
      console.error(err);
      setChatMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: language === "ar"
            ? `❌ تعذر إرسال القيود للمراجعة: ${err.message || err}`
            : `❌ Could not send entries for review: ${err.message || err}`,
        },
      ]);
      throw err;
    } finally {
      setIsSubmittingReview(false);
    }
  };

  const handleChatFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";

    setIsUploading(true);
    setChatLoading(true);
    setChatMessages((prev) => [
      ...prev,
      {
        role: "user",
        text: language === "ar"
          ? `📎 [مرفق] تم اختيار الملف: ${file.name}`
          : `📎 [Attachment] Selected file: ${file.name}`
      },
      {
        role: "assistant",
        text: language === "ar"
          ? `جاري رفع وتحليل المستند "${file.name}"...`
          : `Uploading and analyzing document "${file.name}"...`
      }
    ]);

    try {
      const formData = new FormData();
      formData.append("files", file);
      const uploadRes = await documentsGateway.uploadDocuments({ method: "POST", body: formData });
      if (!uploadRes.ok) throw new Error(await uploadRes.text());

      const uploadData = await uploadRes.json();
      if (uploadData.error_count > 0 || !uploadData.results || uploadData.results.length === 0) {
        throw new Error(uploadData.results?.[0]?.message || "Upload failed");
      }

      const analysisResult = uploadData.results[0].result;
      const fields = analysisResult.fields || {};
      const amount = fields.total_amount || fields.amount || 0;
      const partnerName = fields.supplier_name || fields.partner_name || "";
      const rawText = analysisResult.raw_text_preview || "";
      const analyzedDocumentClass = String(
        analysisResult.document_class || fields.document_class || "unknown",
      );

      if (shouldParseAsBankStatement(file.name, analyzedDocumentClass, rawText)) {
        const selectedJournal = journals.find((journal) => journal.id === selectedJournalId);
        if (!selectedJournal || selectedJournal.type !== "bank") {
          throw new Error(
            language === "ar"
              ? "هذا الملف كشف حساب بنكي. اختر يومية من نوع Bank من قائمة اليومية ثم أعد رفع الملف، حتى يكون حساب البنك وقواعد التسوية من Odoo هي مصدر الحقيقة."
              : "This is a bank statement. Select a Bank-type journal first so the bank account and reconciliation rules come from Odoo, then upload the file again."
          );
        }

        const reviewForm = new FormData();
        reviewForm.append("statement", file);
        reviewForm.append("journal_id", String(selectedJournal.id));
        const prepareRes = await documentsGateway.prepareDailyBankReview({
          method: "POST",
          body: reviewForm,
        });
        if (!prepareRes.ok) throw new Error(await prepareRes.text());
        const prepared = await prepareRes.json();
        const entries = (Array.isArray(prepared.entries) ? prepared.entries : []) as DailyBankReviewEntry[];
        if (prepared.status !== "prepared" || entries.length === 0) {
          throw new Error("Daily bank review preparation returned no entries.");
        }

        const worksheets = buildDailyBankReviewWorksheets(
          entries,
          language,
          DEFAULT_WORKSHEET_ROWS,
          DEFAULT_WORKSHEET_COLUMNS,
        );
        setSheets(worksheets);
        setActiveSheetId(worksheets[0].id);

        const summary = prepared.summary || {};
        const source = prepared.source_document || {};
        const bankJournal = prepared.bank_journal || {};
        const draft: DailyBankReviewDraft = {
          documentId: Number(source.document_id),
          sourceFilename: String(source.filename || file.name),
          sourceSha256: String(source.sha256 || ""),
          journalId: Number(bankJournal.journal_id || selectedJournal.id),
          companyId: bankJournal.company_id ? Number(bankJournal.company_id) : null,
          ruleCount: Number(bankJournal.rule_count || summary.rule_count || 0),
          transactionCount: Number(summary.transaction_count || 0),
          unresolvedCount: Number(summary.unresolved_count || 0),
          lowConfidenceCount: Number(summary.low_confidence_count || 0),
          entries,
          submitted: false,
          reviewIds: [],
        };
        setBankReviewDraft(draft);

        setChatMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            text: language === "ar"
              ? `✅ تم إعداد كشف البنك وفق Odoo Bank Rules.\n\n- الحركات: ${draft.transactionCount.toLocaleString()}\n- القيود اليومية: ${entries.length.toLocaleString()} (قيد واحد لكل يوم)\n- قواعد Odoo المقروءة: ${draft.ruleCount.toLocaleString()}\n- حركات غير محلولة: ${draft.unresolvedCount.toLocaleString()}\n- مطابقات تحتاج انتباه: ${draft.lowConfidenceCount.toLocaleString()}\n\nكل ورقة الآن تمثل قيد يوم كامل مع الاحتفاظ بتفاصيل كل حركة وقاعدة البنك ودليل المطابقة. لم يتم ترحيل أي شيء إلى Odoo. راجع القيود ثم اضغط «إرسال للمراجعة».`
              : `✅ The bank statement was prepared using Odoo Bank Rules.\n\n- Transactions: ${draft.transactionCount.toLocaleString()}\n- Daily entries: ${entries.length.toLocaleString()} (one entry per day)\n- Odoo rules read: ${draft.ruleCount.toLocaleString()}\n- Unresolved transactions: ${draft.unresolvedCount.toLocaleString()}\n- Matches needing attention: ${draft.lowConfidenceCount.toLocaleString()}\n\nEach worksheet now represents one complete daily entry while preserving every transaction and its Bank Rule evidence. Nothing was posted to Odoo. Review the entries, then click “Send for Review”.`,
          },
        ]);
        return;
      }

      setBankReviewDraft(null);
      const selectedJournal = journals.find((journal) => journal.id === selectedJournalId);
      const docClass = analyzedDocumentClass !== "unknown"
        ? analyzedDocumentClass
        : selectedJournal?.type || "general";
      const accountingDate = fields.invoice_date
        || fields.processing_date
        || fields.payment_date
        || fields.transaction_date
        || fields.date
        || new Date().toISOString().slice(0, 10);

      const proposeRes = await documentsGateway.proposeTransaction({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename: file.name,
          document_class: docClass,
          amount,
          date: accountingDate,
          partner_name: partnerName,
          raw_text: rawText,
        }),
      });
      if (!proposeRes.ok) throw new Error(await proposeRes.text());

      const proposeData = await proposeRes.json();
      if (proposeData.status !== "success" || !proposeData.lines) {
        throw new Error(proposeData.message || "Failed to generate proposed lines");
      }

      const proposedLines = proposeData.lines;
      setSheets((prevSheets) => prevSheets.map((sheet) => {
        if (sheet.id !== activeSheetId) return sheet;
        const newGrid = createEmptyGrid();
        newGrid[0][0] = language === "ar" ? "رمز الحساب" : "Account Code";
        newGrid[0][1] = language === "ar" ? "البيان / الوصف" : "Description";
        newGrid[0][2] = language === "ar" ? "مدين" : "Debit";
        newGrid[0][3] = language === "ar" ? "دائن" : "Credit";
        newGrid[0][4] = language === "ar" ? "اسم الشريك" : "Partner";
        newGrid[0][5] = language === "ar" ? "الحساب التحليلي" : "Analytic Account";

        proposedLines.forEach((line: any, idx: number) => {
          const rowIndex = idx + 1;
          if (rowIndex >= DEFAULT_WORKSHEET_ROWS) return;
          const accName = line.account_name || "";
          const accCode = line.account_code || accName.match(/^(\d+)/)?.[1] || accName;
          newGrid[rowIndex][0] = accCode;
          newGrid[rowIndex][1] = line.name || "";
          newGrid[rowIndex][2] = line.debit > 0 ? String(line.debit) : "";
          newGrid[rowIndex][3] = line.credit > 0 ? String(line.credit) : "";
          newGrid[rowIndex][4] = line.partner_name || proposeData.suggested_partner_name || partnerName || "";
          newGrid[rowIndex][5] = line.analytic_account_name || "";
        });

        return {
          ...sheet,
          gridData: newGrid,
          rowCount: newGrid.length,
          colCount: newGrid[0]?.length || DEFAULT_WORKSHEET_COLUMNS,
        };
      }));

      setChatMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: language === "ar"
            ? `✅ تم بنجاح تحليل المستند ومطابقته مع اليومية المحددة.\n\nتم تعبئة البيانات في الجدول بالقيم المحللة:\n- القيمة: ${Number(amount || 0).toLocaleString()} ر.س\n- الشريك المقترح: ${proposeData.suggested_partner_name || partnerName || "غير محدد"}\n- نوع القيد: ${proposeData.journal_name}`
            : `✅ Successfully analyzed and matched document with the selected journal.\n\nSpreadsheet has been populated:\n- Amount: ${Number(amount || 0).toLocaleString()} SAR\n- Suggested Partner: ${proposeData.suggested_partner_name || partnerName || "N/A"}\n- Entry Type: ${proposeData.journal_name}`
        }
      ]);
    } catch (err: any) {
      console.error(err);
      setChatMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: language === "ar"
            ? `❌ فشل تحليل أو معالجة المستند: ${err.message || err}`
            : `❌ Failed to analyze or process the document: ${err.message || err}`
        }
      ]);
    } finally {
      setIsUploading(false);
      setChatLoading(false);
    }
  };

  return {
    isUploading,
    isSubmittingReview,
    bankReviewDraft,
    chatMessages,
    chatInput,
    setChatInput,
    chatLoading,
    chatMessagesEndRef,
    chatFileInputRef,
    handleSendChatMessage,
    handleChatFileChange,
    submitBankReview,
  };
}
