# GuardianAI Accountant & Auditor Enterprise

Enterprise-grade AI accounting, auditing, tax compliance, and ERP execution platform.

## Structure

- `backend/`  FastAPI backend (Python)
- `frontend/` Next.js frontend (TypeScript)
- `storage/`  Local development storage

## Prerequisites

- **Python** 3.11+
- **Node.js** 20+
- **PostgreSQL** 15+
- **Tesseract OCR** (for document scanning)

## Backend Setup

```bash
cd BOB-2/backend

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment variables
cp ../.env.example ../.env
# Edit ../.env with your database URL, secret key, etc.

# Run database migrations
alembic upgrade head

# Start the backend server
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

The backend runs at `http://127.0.0.1:8000`. API docs available at `/docs` in non-production mode.

## Frontend Setup

```bash
cd BOB-2/frontend

# Install dependencies
npm install

# Start the development server
npm run dev
```

The frontend runs at `http://localhost:3000`.

## Environment Variables

Copy `.env.example` to `.env` in the project root and configure:

| Variable | Description | Default |
|----------|-------------|---------|
| `APP_NAME` | Application display name | GuardianAI Accountant & Auditor Enterprise |
| `APP_ENV` | Environment (`local`, `production`) | `local` |
| `BACKEND_HOST` | Backend bind host | `127.0.0.1` |
| `BACKEND_PORT` | Backend bind port | `8000` |
| `FRONTEND_ORIGIN` | Frontend URL for CORS | `http://localhost:3000` |
| `DATABASE_URL` | PostgreSQL connection string | (see `.env.example`) |
| `SECRET_KEY` | JWT signing key (auto-generated in dev) | (empty) |
| `ODOO_URL` | Odoo instance URL | |
| `ODOO_DB` | Odoo database name | |
| `ODOO_USERNAME` | Odoo login username | |
| `ODOO_PASSWORD` | Odoo login password / API key | |

> **Security note:** In production, always set `SECRET_KEY` to a strong random value. Generate one with: `openssl rand -hex 64`

## Initial Owner Provisioning

Production does **not** create a default owner account and the application does
not ship with a default password. Provision the first owner through the approved
deployment procedure and secret store. Keep `GUARDIAN_SEED_EMAIL` and
`GUARDIAN_SEED_PASSWORD` empty in production after provisioning.

Never publish seed credentials in documentation, source control, images, or
deployment logs.

## Features

- Odoo ERP integration via XML-RPC (v16 - v19)
- Autonomous financial structure discovery (accounts, journals, taxes, partners, products, employees)
- Document AI with OCR (invoices, receipts) supporting Arabic and English
- Smart document matching against ERP transactions
- Interactive spreadsheet with AI chat assistant
- Audit control room with attachment detection
- Telegram bot for mobile document processing
- Enterprise RBAC (Owner, Admin, Accountant, Auditor, CFO, Viewer)
- JWT authentication with bcrypt password hashing
- Fernet encryption for stored credentials
- Audit logging middleware
- Bilingual UI (Arabic RTL / English LTR)

## Accounting AI Matching Engine

BOB includes an audit-safe Accounting & Finance AI Matching Engine for invoices, receipts, payment vouchers, purchase orders, bank statements, journal entries, trial balances, and vendor bills.

### Install backend dependencies

```bash
cd BOB-2/backend
pip install -r requirements.txt
```

The default embedding provider is sentence-transformers compatible and is configured with:

```bash
export EMBEDDING_MODEL_NAME=BAAI/bge-m3
```

BGE-M3-style models produce 1024-dimensional vectors. If the sentence-transformers model is unavailable in an offline environment, the backend falls back to a deterministic local accounting text embedding so the audit workflow remains usable without paid external APIs.

### Database migration

```bash
cd BOB-2/backend
alembic upgrade head
```

This creates:

- `ai_document_embeddings`
- `ai_document_matches`
- `ai_accounting_suggestions`
- `ai_decision_audit_log`

### Run backend

```bash
cd BOB-2/backend
APP_ENV=local DATABASE_URL="sqlite:///./local_accounting_ai.db" SECRET_KEY="local-secret-key-for-dev-1234567890abcdef" python -m uvicorn app.main:app --reload --port 8000
```

### Run frontend

```bash
cd BOB-2/frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```

Open `/accounting-ai`, paste extracted OCR/accounting text, choose the source type, and run analysis. The page shows document classification, semantic matches, a draft journal-entry suggestion, confidence scores, explanations, and approve/reject buttons. Approval only stores review status; it does not post entries to ERP automatically.

## Product Boundaries

- GuardianAI assists authorized finance professionals; it does not replace
  accounting judgment or customer approval controls.
- The current production integration target is Odoo. SAP and Oracle are not
  advertised as supported until dedicated connectors pass integration testing.
- The current release is not an independently certified ZATCA e-invoicing
  solution.
- Production financial posting requires an authorized human approval and an
  approved customer UAT sign-off.
- Closed-source commercial release remains blocked until the third-party PDF
  dependency licensing finding in `release/THIRD_PARTY_LICENSE_REVIEW.md` is
  resolved with retained evidence.

### Test the AI matching flow

1. Paste an invoice or vendor bill text with supplier, VAT, and amount details.
2. Run **Analyze & Match**.
3. Paste a related PO, payment voucher, or bank transaction and run analysis again.
4. Review suggested matches and journal entry draft.
5. Approve or reject the draft; the backend writes an AI decision audit log and performs no ERP posting.
