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

## Default Seed User

On first startup the backend seeds a default owner account:

- **Email:** `owner@guardian.local`
- **Password:** value of `GUARDIAN_SEED_PASSWORD` env var, or `Owner@Seed#2026!`
- **Role:** `owner`

Change this password immediately after first login.

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
