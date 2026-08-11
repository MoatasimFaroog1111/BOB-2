"use client";

import { useCallback, useEffect, useState } from "react";

import { erpSettingsGateway } from "./api";
import type {
  ERPConnection,
  ERPConnectionInput,
  ERPConnectionTestResult,
  ERPProviderDefinition,
} from "./types";

const EMPTY_FORM: ERPConnectionInput = {
  provider: "odoo",
  url: "",
  db: "",
  username: "",
  password: "",
};

export function useERPConnectionSettings(onSaved?: () => void) {
  const [form, setForm] = useState<ERPConnectionInput>(EMPTY_FORM);
  const [savedConnection, setSavedConnection] = useState<ERPConnection | null>(null);
  const [providers, setProviders] = useState<ERPProviderDefinition[]>([]);
  const [testResult, setTestResult] = useState<ERPConnectionTestResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const [connection, providerCatalog] = await Promise.all([
        erpSettingsGateway.getSavedConnection(),
        erpSettingsGateway.listProviders(),
      ]);
      setProviders(providerCatalog);
      setSavedConnection(connection);
      if (connection) {
        setForm({
          provider: connection.provider,
          url: connection.url,
          db: connection.db,
          username: connection.username,
          password: "",
        });
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "تعذر تحميل اتصال النظام المحاسبي.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const perform = useCallback(async (operation: () => Promise<void>) => {
    setWorking(true);
    setError("");
    setMessage("");
    try {
      await operation();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "تعذر تنفيذ العملية على النظام المحاسبي.");
    } finally {
      setWorking(false);
    }
  }, []);

  const testDraft = () =>
    perform(async () => {
      if (!providers.find((provider) => provider.key === form.provider)?.implemented) {
        throw new Error("الموصل المحدد ظاهر في الكتالوج لكنه غير منفذ بعد، لذلك لن يتم ادعاء اتصال غير حقيقي.");
      }
      if (!form.url || !form.db || !form.username || !form.password) {
        throw new Error("أكمل رابط Odoo وقاعدة البيانات واسم المستخدم وكلمة المرور أولًا.");
      }
      const result = await erpSettingsGateway.testConnection(form);
      setTestResult(result);
      setMessage(result.connected ? "نجح اختبار الاتصال بالبيانات المدخلة." : "لم ينجح اختبار الاتصال.");
    });

  const testSaved = () =>
    perform(async () => {
      const result = await erpSettingsGateway.testSavedConnection();
      setTestResult(result);
      setMessage(result.connected ? "الاتصال المحفوظ يعمل بصورة صحيحة." : "الاتصال المحفوظ غير متاح.");
    });

  const save = () =>
    perform(async () => {
      if (!providers.find((provider) => provider.key === form.provider)?.implemented) {
        throw new Error("لا يمكن حفظ هذا النظام قبل تثبيت موصله الفعلي.");
      }
      if (!form.url || !form.db || !form.username || !form.password) {
        throw new Error("أدخل كلمة المرور أو مفتاح API مع بقية بيانات الاتصال قبل الحفظ.");
      }
      const connection = await erpSettingsGateway.saveConnection(form);
      setSavedConnection(connection);
      setForm((current) => ({ ...current, password: "" }));
      setMessage("تم التحقق من الاتصال وحفظه وتفعيله لهذه المؤسسة.");
      onSaved?.();
    });

  return {
    form,
    setForm,
    savedConnection,
    providers,
    testResult,
    loading,
    working,
    error,
    message,
    testDraft,
    testSaved,
    save,
  };
}
