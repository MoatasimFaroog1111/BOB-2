# Centralized tenant secret store

## Production boundary

Production accepts only `azure_key_vault`. The backend authenticates with Azure Managed Identity and never receives a long-lived Key Vault credential. Secret values are not stored in PostgreSQL, application storage, source control, logs, API responses, or ordinary production environment variables.

The database stores only tenant-scoped metadata:

- organization and approved purpose;
- remote provider and opaque secret name;
- current remote version;
- SHA-256 fingerprint;
- active/revoked state;
- creating, rotating, and revoking users and timestamps;
- append-only version metadata.

Supported purposes are intentionally closed: Telegram bot token, external LLM API key, and ERP credentials.

## Rotation

Saving a value for an existing organization/purpose creates a new Key Vault version. The previous metadata version becomes `superseded`; the new version becomes `active`. Consumers resolve the current version at use time, so rotation does not require storing the value in configuration or restarting solely to change the credential.

## Revocation

Revocation disables the current Key Vault version before marking the binding revoked. Resolution then fails closed. Telegram does not start without an active tenant token. External LLM processing returns a blocked credential state. ERP credential resolution fails rather than accepting old local ciphertext.

## Azure permissions

Grant the backend Managed Identity only the smallest data-plane permissions needed for the application vault:

- read the selected version;
- create a new version;
- update attributes to disable a version.

Do not grant vault administration, purge, key management, certificate management, or broad subscription permissions to the application identity.

## Network controls

The vault URL must be an exact HTTPS `*.vault.azure.net` hostname. Userinfo, query strings, fragments, custom ports, paths, private/link-local/loopback DNS answers, redirects, and proxy tunnels are rejected. TLS validates the original vault hostname while the socket is pinned to the addresses that passed validation. Managed Identity token acquisition is limited to the Azure platform endpoint or a validated loopback App Service identity endpoint.

## Legacy migration

Local Fernet files and keys are no longer read. Legacy ERP database fields may retain the historical column name `encrypted_secret_ref`, but new values are versioned `secretref://` references rather than ciphertext. Existing Fernet ciphertext must be rotated by an authorized administrator into Key Vault; the application deliberately refuses to decrypt it after this stage.

## Operational gate

Before a backend production deployment:

1. create or select the dedicated Key Vault;
2. enable a system-assigned or user-assigned Managed Identity on the backend;
3. grant the minimum vault secret permissions;
4. configure the exact vault URL and optional managed identity client ID;
5. apply Alembic revision `9c7f2a4b1d80`;
6. rotate each Telegram, ERP, and LLM credential through the authenticated tenant administration endpoint;
7. verify audit events and revoke any old local/environment credentials;
8. keep Telegram and external LLM execution disabled until their separate production gates are approved.
