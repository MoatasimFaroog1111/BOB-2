"use client";

import { useCallback, useEffect, useState } from "react";

import { erpSettingsGateway } from "./api";
import { getERPProviderDefinition, isERPProviderId } from "./providers";
import type {
  ERPConnection,
  ERPConnectionInput,
  ERPConnectionTestResult,
  ERPProviderId,
} from "./types";

const EMPTY_FORM: ERPConnectionInput = {
  provider: "odoo",
  url: "",
  db: "",
  username: "",
  password: "",
};

function validateForm(form: ERPConnectionInput): void {
  const definition = getERPProviderDefinition(form.provider);
  if (!form.url.trim()) {
    throw new Error(`أدخل ${definition.urlLabel} أولًا.`);
  }
  if (definition.requiresDb && !form.db.trim()) {
    throw new Error(`أدخل ${definition.dbLabel} أولًا.`);
  }
  if (definition.requiresUsername && !form.username.trim()) {
    throw new Error(`أدخل ${definition.usernameLabel} أولًا.`);
  }
  if (!form.password.trim()) {
    throw new Error(`أدخل ${definition.passwordLabel} أولًا.`);
  }
}

export function useERPConnectionSettings(onSaved?: () => void) {
  const [form, setForm] = useState<ERPConnectionInput>(EMPTY_FORM);
  const [savedConnection, setSavedConnection] = useState<ERPConnection | null>(null);
  const [testResult, setTestResult] = useState<ERPConnectionTestResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const connection = await erpSettingsGateway.getSavedConnection();
      setSavedConnection(connection);
      if (connection) {
        const provider: ERPProviderId = isERPProviderId(connection.provider)
          ? connection.provider
          : "odoo";
        setForm({
          provider,
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

  const selectProvider = (provider: ERPProviderId) => {
    const definition = getERPProviderDefinition(provider);
    setTestResult(null);
    setForm({
      provider,
      url: definition.defaultUrl || "",
      db: "",
      username: "",
      password: "",
    });
  };

  const testDraft = () =>
    perform(async () => {
      validateForm(form);
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
      validateForm(form);
      const connection = await erpSettingsGateway.saveConnection(form);
      setSavedConnection(connection);
      setForm((current) => ({ ...current, password: "" }));
      setMessage("تم التحقق من الاتصال وحفظه وتفعيله لهذه المؤسسة.");
      onSaved?.();
    });

  return {
    form,
    setForm,
    selectProvider,
    savedConnection,
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
