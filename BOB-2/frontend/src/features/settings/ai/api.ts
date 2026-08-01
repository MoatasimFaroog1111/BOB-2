import { requestJson } from "@/features/settings/shared/http";

import type {
  CredentialStatus,
  ExternalAIPolicyInput,
  ExternalAISettings,
} from "./types";

export interface ExternalAISettingsGateway {
  load(): Promise<ExternalAISettings>;
  saveCredential(apiKey: string): Promise<CredentialStatus>;
  revokeCredential(): Promise<CredentialStatus>;
  savePolicy(payload: ExternalAIPolicyInput): Promise<ExternalAISettings>;
}

class HttpExternalAISettingsGateway implements ExternalAISettingsGateway {
  load(): Promise<ExternalAISettings> {
    return requestJson<ExternalAISettings>("/api/v1/llm/policy");
  }

  saveCredential(apiKey: string): Promise<CredentialStatus> {
    return requestJson<CredentialStatus>("/api/v1/llm/credential", {
      method: "PUT",
      body: JSON.stringify({ api_key: apiKey }),
    });
  }

  revokeCredential(): Promise<CredentialStatus> {
    return requestJson<CredentialStatus>("/api/v1/llm/credential", {
      method: "DELETE",
    });
  }

  savePolicy(payload: ExternalAIPolicyInput): Promise<ExternalAISettings> {
    return requestJson<ExternalAISettings>("/api/v1/llm/policy", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  }
}

export const externalAISettingsGateway: ExternalAISettingsGateway =
  new HttpExternalAISettingsGateway();
