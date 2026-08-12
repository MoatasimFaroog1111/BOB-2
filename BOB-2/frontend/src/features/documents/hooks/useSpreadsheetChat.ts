import React, { useEffect, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import { documentsGateway } from "@/features/documents/api/documentsGateway";
import {
  buildBankStatementGrid,
  shouldParseAsBankStatement,
} from "@/features/documents/lib/bankStatementImport";
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
  // Journals States
  const [isUploading, setIsUploading] = useState(false);

  const chatMessagesEndRef = useRef<HTMLDivElement>(null);
  const chatFileInputRef = useRef<HTMLInputElement>(null);

  // Chat States
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

  // Auto scroll chat to bottom
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
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          prompt: userMsg,
          sheets: sheets.map(s => ({
            id: s.id,
            name: s.name,
            gridData: s.gridData,
            rowCount: s.rowCount,
            colCount: s.colCount,
          })),
          active_sheet_id: activeSheetId,
        }),
      });

      if (!res.ok) {
        throw new Error(await res.text());
      }

      const data = await res.json();
      
      // Add agent's response to message feed
      if (data.message) {
        setChatMessages((prev) => [...prev, { role: "assistant", text: data.message }]);
      }

      // Synchronize states
      setSheets((prevSheets) => {
        let updated = [...prevSheets];

        // 1. Handle Active Sheet Grid Data Update
        if (data.grid_data && Array.isArray(data.grid_data)) {
          updated = updated.map((s) => {
            if (s.id !== activeSheetId) return s;
            const newGrid = data.grid_data;
            const newRowCount = newGrid.length;
            const newColCount = newGrid[0]?.length || 0;
            return {
              ...s,
              gridData: newGrid,
              rowCount: newRowCount,
              colCount: newColCount,
            };
          });
        }

        // 2. Handle Rename Active Sheet
        if (data.active_sheet_name) {
          updated = updated.map((s) => 
            s.id === activeSheetId ? { ...s, name: data.active_sheet_name } : s
          );
        }

        // 3. Handle Create Sheet
        if (data.create_sheet && data.create_sheet.name) {
          const newId = `sheet-${Date.now()}`;
          const newGrid = data.create_sheet.grid_data || createEmptyGrid();
          const rowCount = newGrid.length;
          const colCount = newGrid[0]?.length || 0;
          
          updated.push({
            id: newId,
            name: data.create_sheet.name,
            gridData: newGrid,
            rowCount,
            colCount,
          });
          // Set active sheet to the newly created one
          setTimeout(() => setActiveSheetId(newId), 50);
        }

        // 4. Handle Delete Sheet
        if (data.delete_sheet_id) {
          if (updated.length > 1) {
            const idToDelete = data.delete_sheet_id;
            updated = updated.filter((s) => s.id !== idToDelete);
            if (activeSheetId === idToDelete) {
              setActiveSheetId(updated[updated.length - 1].id);
            }
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

  const handleChatFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Reset input value to allow uploading same file again
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
      // Upload and analyze through the feature gateway.
      const formData = new FormData();
      formData.append("files", file);

      const uploadRes = await documentsGateway.uploadDocuments({
        method: "POST",
        body: formData,
      });

      if (!uploadRes.ok) {
        throw new Error(await uploadRes.text());
      }

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

      // Bank statements are multi-transaction documents. Never collapse them into one
      // two-line proposal based on the first fee/amount discovered in the workbook.
      if (shouldParseAsBankStatement(file.name, analyzedDocumentClass, rawText)) {
        const statementFormData = new FormData();
        statementFormData.append("statement", file);

        const statementRes = await documentsGateway.parseBankStatement({
          method: "POST",
          body: statementFormData,
        });

        if (statementRes.ok) {
          const statementData = await statementRes.json();
          const statementRows = Array.isArray(statementData.statement_only)
            ? statementData.statement_only
            : [];

          if (statementData.status === "success" && statementRows.length > 0) {
            const statementGrid = buildBankStatementGrid(
              statementRows,
              language,
              DEFAULT_WORKSHEET_ROWS,
              DEFAULT_WORKSHEET_COLUMNS,
            );

            setSheets((prevSheets) => prevSheets.map((sheet) => (
              sheet.id === activeSheetId
                ? {
                    ...sheet,
                    gridData: statementGrid.gridData,
                    rowCount: statementGrid.rowCount,
                    colCount: statementGrid.colCount,
                  }
                : sheet
            )));

            setChatMessages((prev) => [
              ...prev,
              {
                role: "assistant",
                text: language === "ar"
                  ? `✅ تم التعرف على الملف ككشف حساب بنكي وتحليل ${statementRows.length.toLocaleString()} عملية.\n\nتم تعبئة الجدول مباشرة من معاملات كشف الحساب (التاريخ، الوصف، المدين، الدائن، التصنيف المقترح، الرصيد). لم يتم اختزال الكشف إلى عملية واحدة ولم يتم الترحيل إلى Odoo؛ راجع التصنيفات قبل إنشاء القيود.`
                  : `✅ The file was recognized as a bank statement and ${statementRows.length.toLocaleString()} transactions were parsed.\n\nThe grid now contains the statement transactions (date, description, debit, credit, suggested classification, balance). The statement was not collapsed into a single transaction and nothing was posted to Odoo; review the classifications before creating entries.`
              }
            ]);
            return;
          }
        } else {
          console.warn("Bank statement parser did not accept the file; falling back to document proposal flow.");
        }
      }

      // Request a draft transaction through the feature gateway.
      const selectedJournal = journals.find((j) => j.id === selectedJournalId);
      const docClass = analyzedDocumentClass !== "unknown"
        ? analyzedDocumentClass
        : selectedJournal?.type || "general";
      const accountingDate = fields.invoice_date
        || fields.processing_date
        || fields.payment_date
        || fields.transaction_date
        || fields.date
        || new Date().toISOString().slice(0, 10);

      const proposePayload = {
        filename: file.name,
        document_class: docClass,
        amount: amount,
        date: accountingDate,
        partner_name: partnerName,
        raw_text: rawText,
      };

      const proposeRes = await documentsGateway.proposeTransaction({
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(proposePayload),
      });

      if (!proposeRes.ok) {
        throw new Error(await proposeRes.text());
      }

      const proposeData = await proposeRes.json();
      if (proposeData.status !== "success" || !proposeData.lines) {
        throw new Error(proposeData.message || "Failed to generate proposed lines");
      }

      const proposedLines = proposeData.lines;

      // 3. Clear and populate active sheet gridData
      setSheets((prevSheets) => {
        return prevSheets.map((s) => {
          if (s.id !== activeSheetId) return s;

          const newGrid = createEmptyGrid();

          // Set Headers
          newGrid[0][0] = language === "ar" ? "رمز الحساب" : "Account Code";
          newGrid[0][1] = language === "ar" ? "البيان / الوصف" : "Description";
          newGrid[0][2] = language === "ar" ? "مدين" : "Debit";
          newGrid[0][3] = language === "ar" ? "دائن" : "Credit";
          newGrid[0][4] = language === "ar" ? "اسم الشريك" : "Partner";
          newGrid[0][5] = language === "ar" ? "الحساب التحليلي" : "Analytic Account";

          proposedLines.forEach((line: any, idx: number) => {
            const rIdx = idx + 1;
            if (rIdx >= DEFAULT_WORKSHEET_ROWS) return;

            const accName = line.account_name || "";
            const accCode = line.account_code || accName.match(/^(\d+)/)?.[1] || accName;

            newGrid[rIdx][0] = accCode;
            newGrid[rIdx][1] = line.name || "";
            newGrid[rIdx][2] = line.debit > 0 ? String(line.debit) : "";
            newGrid[rIdx][3] = line.credit > 0 ? String(line.credit) : "";
            newGrid[rIdx][4] = line.partner_name || proposeData.suggested_partner_name || partnerName || "";
            newGrid[rIdx][5] = line.analytic_account_name || "";
          });

          return {
            ...s,
            gridData: newGrid,
            rowCount: newGrid.length,
            colCount: newGrid[0]?.length || DEFAULT_WORKSHEET_COLUMNS,
          };
        });
      });

      setChatMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: language === "ar"
            ? `✅ تم بنجاح تحليل المستند ومطابقته مع اليومية المحددة.\n\nتم تعبئة البيانات في الجدول بالقيم المحللة:\n- القيمة: ${amount.toLocaleString()} ر.س\n- الشريك المقترح: ${proposeData.suggested_partner_name || partnerName || "غير محدد"}\n- نوع القيد: ${proposeData.journal_name}`
            : `✅ Successfully analyzed and matched document with the selected journal.\n\nSpreadsheet has been populated:\n- Amount: ${amount.toLocaleString()} SAR\n- Suggested Partner: ${proposeData.suggested_partner_name || partnerName || "N/A"}\n- Entry Type: ${proposeData.journal_name}`
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
    chatMessages,
    chatInput,
    setChatInput,
    chatLoading,
    chatMessagesEndRef,
    chatFileInputRef,
    handleSendChatMessage,
    handleChatFileChange,
  };
}

