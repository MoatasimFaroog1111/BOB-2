import {
  requestJson,
  SettingsApiError,
} from "@/features/settings/shared/http";

import type {
  ERPConnection,
  ERPConnectionInput,
  ERPConnectionTestResult,
  ERPProviderDefinition,
} from "./types";

export interface ERPSettingsGateway {
  getSavedConnection(): Promise<ERPConnection | null>;
  testConnection(payload: ERPConnectionInput): Promise<ERPConnectionTestResult>;
  testSavedConnection(): Promise<ERPConnectionTestResult>;
  saveConnection(payload: ERPConnectionInput): Promise<ERPConnection>;
  listProviders(): Promise<ERPProviderDefinition[]>;
}

class HttpERPSettingsGateway implements ERPSettingsGateway {
  async listProviders(): Promise<ERPProviderDefinition[]> {
    const response = await requestJson<{ providers: ERPProviderDefinition[] }>("/api/v1/erp/providers");
    return response.providers;
  }

  async getSavedConnection(): Promise<ERPConnection | null> {
    try {
      return await requestJson<ERPConnection>("/api/v1/erp/connection");
    } catch (cause) {
      if (cause instanceof SettingsApiError && cause.status === 404) {
        return null;
      }
      throw cause;
    }
  }

  testConnection(payload: ERPConnectionInput): Promise<ERPConnectionTestResult> {
    return requestJson<ERPConnectionTestResult>("/api/v1/erp/test-connection", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  testSavedConnection(): Promise<ERPConnectionTestResult> {
    return requestJson<ERPConnectionTestResult>("/api/v1/erp/test-saved", {
      method: "POST",
    });
  }

  saveConnection(payload: ERPConnectionInput): Promise<ERPConnection> {
    return requestJson<ERPConnection>("/api/v1/erp/connection", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }
}

export const erpSettingsGateway: ERPSettingsGateway =
  new HttpERPSettingsGateway();
