export type ERPConnectionInput = {
  provider: string;
  url: string;
  db: string;
  username: string;
  password: string;
};

export type ERPProviderDefinition = {
  key: string;
  display_name: string;
  category: string;
  market: string;
  implemented: boolean;
  description: string;
};

export type ERPConnection = {
  id: number;
  provider: string;
  url: string;
  db: string;
  username: string;
  is_active: boolean;
};

export type ERPConnectionTestResult = {
  connected: boolean;
  uid?: number;
  username?: string;
  odoo_version?: {
    server_version?: string;
    server_version_info?: unknown[];
  };
  [key: string]: unknown;
};
