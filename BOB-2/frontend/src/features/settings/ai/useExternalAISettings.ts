"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { externalAISettingsGateway } from "./api";
import type {
  ExternalAIPolicyForm,
  ExternalAIPolicyInput,
  ExternalAISettings,
} from "./types";

const EMPTY_FORM: ExternalAIPolicyForm = {
  external_llm_enabled: false,
  approved_provider: "",
  approved_model: "",
  allowed_purposes: [],
  allow_redacted_document_text: false,
  allow_financial_values: false,
  max_redacted_text_chars: 0,
  dpa_version: "",
  dpa_reference: "",
  data_residency_region: "",
  provider_retention_mode: "",
  accept_dpa: false,
};

function settingsToForm(settings: ExternalAISettings): ExternalAIPolicyForm {
  const policy = settings.policy;
  const firstProvider = settings.globally_allowed_providers[0] || "";
  const firstModel = settings.globally_allowed_models
    .find((value) => value.startsWith(`${firstProvider}:`))
    ?.slice(firstProvider.length + 1) || "";

  if (!policy) {
    return {
      ...EMPTY_FORM,
      approved_provider: firstProvider,
      approved_model: firstModel,
      dpa_version: settings.required_dpa_version,
      provider_retention_mode: settings.available_retention_modes[0] || "",
    };
  }

  return {
    external_llm_enabled: policy.external_llm_enabled,
    approved_provider: policy.approved_provider || "",
    approved_model: policy.approved_model || "",
    allowed_purposes: policy.allowed_purposes || [],
    allow_redacted_document_text: policy.allow_redacted_document_text,
    allow_financial_values: policy.allow_financial_values,
    max_redacted_text_chars: policy.max_redacted_text_chars,
    dpa_version: policy.dpa_version || settings.required_dpa_version,
    dpa_reference: policy.dpa_reference || "",
    data_residency_region: policy.data_residency_region || "",
    provider_retention_mode:
      policy.provider_retention_mode || settings.available_retention_modes[0] || "",
    accept_dpa: false,
  };
}

function formToPayload(form: ExternalAIPolicyForm): ExternalAIPolicyInput {
  return {
    ...form,
    approved_provider: form.approved_provider || null,
    approved_model: form.approved_model || null,
    dpa_version: form.dpa_version || null,
    dpa_reference: form.dpa_reference || null,
    data_residency_region: form.data_residency_region || null,
    provider_retention_mode: form.provider_retention_mode || null,
    max_redacted_text_chars: form.allow_redacted_document_text
      ? form.max_redacted_text_chars
      : 0,
  };
}

export function useExternalAISettings() {
  const [settings, setSettings] = useState<ExternalAISettings | null>(null);
  const [form, setForm] = useState<ExternalAIPolicyForm>(EMPTY_FORM);
  const [apiKey, setApiKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const loaded = await externalAISettingsGateway.load();
      setSettings(loaded);
      setForm(settingsToForm(loaded));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "تعذر تحميل إعدادات الذكاء الاصطناعي.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const modelOptions = useMemo(() => {
    if (!settings || !form.approved_provider) return [];
    return settings.provider_catalog
      .find((provider) => provider.key === form.approved_provider)
      ?.models.filter((model) => model.enabled) ?? [];
  }, [form.approved_provider, settings]);

  const perform = useCallback(async (operation: () => Promise<void>) => {
    setSaving(true);
    setError("");
    setMessage("");
    try {
      await operation();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "تعذر حفظ إعدادات الذكاء الاصطناعي.");
    } finally {
      setSaving(false);
    }
  }, []);

  const saveCredential = () =>
    perform(async () => {
      const value = apiKey.trim();
      if (value.length < 20) {
        throw new Error("أدخل مفتاح API صحيحًا قبل الحفظ.");
      }
      await externalAISettingsGateway.saveCredential(value);
      setApiKey("");
      setMessage("تم حفظ مفتاح الاتصال في مخزن الأسرار المركزي دون عرضه في الواجهة.");
      await load();
    });

  const revokeCredential = () =>
    perform(async () => {
      await externalAISettingsGateway.revokeCredential();
      setMessage("تم إلغاء مفتاح الاتصال وتعطيل استخدامه لهذه المؤسسة.");
      await load();
    });

  const savePolicy = () =>
    perform(async () => {
      const updated = await externalAISettingsGateway.savePolicy(formToPayload(form));
      setSettings(updated);
      setForm(settingsToForm(updated));
      setMessage("تم حفظ مزود الذكاء الاصطناعي والنموذج وسياسة الاستخدام.");
    });

  const testConnection = () =>
    perform(async () => {
      const result = await externalAISettingsGateway.testConnection();
      setMessage(result.connected
        ? `نجح الاتصال بـ ${result.provider} باستخدام ${result.model}.`
        : "فشل اختبار الاتصال بالنموذج الخارجي.");
    });

  return {
    settings,
    form,
    setForm,
    apiKey,
    setApiKey,
    loading,
    saving,
    error,
    message,
    modelOptions,
    saveCredential,
    revokeCredential,
    savePolicy,
    testConnection,
  };
}
