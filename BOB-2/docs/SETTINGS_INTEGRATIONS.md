# Settings-managed integrations

## Navigation

Integration credentials are managed under **Settings & Integrations**:

- `/settings/ai` — external AI provider, model, tenant API key, consent, DPA, retention, and disclosure scope.
- `/settings/accounting-systems` — Odoo URL, database, username, password/API key, saved connection test, and discovery link.

Legacy `/admin/llm` and `/erp` URLs redirect to the new settings pages.

## Local-first AI runtime

The compatibility chat facade always tries the loopback Ollama model first. When the local model is disabled, unavailable, or returns no usable response, it asks an injected secondary-provider factory for a provider.

For authenticated tenant requests, the runtime resolves:

- provider and model from the tenant policy saved in Settings;
- API key from the tenant secret store;
- consent, DPA validity, and the explicit `accounting_reasoning` purpose from the tenant policy;
- endpoint, host allowlist, timeout, response size, and output limits from deployment configuration.

An environment `OPENAI_API_KEY` is never used as a substitute when a tenant scope exists. Missing, revoked, invalid, cross-tenant, or purpose-ineligible settings fail closed.

Background processes without a tenant scope retain the explicitly configured deployment-only fallback for compatibility.

## Required deployment gates for OpenAI fallback

The UI can save tenant settings while deployment gates remain disabled. To permit the local-first OpenAI fallback in an environment, configure the deployment with an exact provider/model allowlist and keep secrets out of environment variables for tenant requests:

```dotenv
LOCAL_LLM_ENABLED=true
EXTERNAL_LLM_ENABLED=true
OPENAI_FALLBACK_ENABLED=true
OPENAI_API_URL=https://api.openai.com/v1/responses
OPENAI_ALLOWED_HOSTS=api.openai.com
EXTERNAL_LLM_ALLOWED_PROVIDERS=openai
EXTERNAL_LLM_ALLOWED_MODELS=openai:gpt-5-mini
```

Then select **openai / gpt-5-mini**, enable the **accounting_reasoning** purpose, and save the API key from `/settings/ai`.

`ACCOUNTING_LLM_PROVIDER` and `ACCOUNTING_LLM_API_URL` belong to the separately audited external accounting-reasoning gateway; they do not configure the local-first fallback.

## SOLID boundaries

- **Single Responsibility:** transport, settings lookup, secret lookup, state management, and presentation are separate modules.
- **Open/Closed:** settings sections and provider configuration sources can be extended without changing page routing or the local chat facade.
- **Liskov Substitution:** alternate settings gateways and provider/configuration implementations satisfy small stable interfaces.
- **Interface Segregation:** AI and ERP features depend only on their own gateway operations.
- **Dependency Inversion:** UI controllers depend on gateway contracts, and the OpenAI provider depends on a configuration-source contract rather than database or environment details.

## Secret handling

- AI keys are write-only in the browser and stored through the tenant secret-store binding.
- ERP passwords/API keys are write-only in the browser and encrypted by the backend.
- Neither secret is returned to the frontend after saving.
