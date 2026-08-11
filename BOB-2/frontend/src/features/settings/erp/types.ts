export type ERPProviderId =
  | "odoo"
  | "sap_s4hana"
  | "oracle_fusion"
  | "business_central"
  | "quickbooks_online"
  | "xero";

export type ERPConnectionInput = {
  provider: ERPProviderId;
  url: string;
  db: string;
  username: string;
  password: string;
};

export type ERPConnection = {
  id: number;
  provider: ERPProviderId | string;
  url: string;
  db: string;
  username: string;
  is_active: boolean;
};

export type ERPConnectionTestResult = {
  connected: boolean;
  provider?: string;
  system?: string;
  uid?: number;
  username?: string;
  odoo_version?: {
    server_version?: string;
    server_version_info?: unknown[];
  };
  [key: string]: unknown;
};
