---
name: testing-guardianai-frontend
description: Test GuardianAI frontend UI changes end-to-end. Use when verifying sidebar, toolbar, documents page, ERP page, or bank reconciliation UI changes.
---

# Testing GuardianAI Frontend

## Architecture

- **Frontend:** Next.js 16.2.7 (App Router) at `BOB-2/frontend/`
- **Backend:** FastAPI at `BOB-2/backend/`
- **Production Frontend:** `https://bob-front-end-production.up.railway.app`
- **Production Backend:** `https://bob-2-production.up.railway.app`

## Local Dev Setup

```bash
cd BOB-2/frontend
npm install  # if node_modules missing
NEXT_PUBLIC_API_BASE_URL=https://bob-2-production.up.railway.app npx next dev -p 3000
```

The frontend runs on `localhost:3000` and connects to the production backend for API calls. This is the recommended way to test UI-only changes without needing a local backend.

## Key Pages & Routes

| Route | Page | Key Features |
|-------|------|-------------|
| `/bank-reconciliation` | Bank Reconciliation AI | Upload, 10 dashboard cards, 4 tabbed tables, Excel/PDF export |
| `/documents` | Document Intelligence | Toolbar, grid, AI assistant, OCR |
| `/audit` | Audit Control Room | Account fetching, attachments |
| `/accounting-ai` | Accounting AI Matching | Semantic matching |
| `/agents` | AI Accounting Agents | Agent management |
| `/erp` | ERP Connections | Odoo setup, Telegram bot config |
| `/team` | Team Management | User list, roles |
| `/settings` | Settings | Language toggle (AR/EN), system info |

## Testing Tips

- **Sidebar navigation** is rendered by `src/components/layout/MainNavigation.tsx` and uses `usePathname()` from `next/navigation` for active state detection. Active page gets amber/gold highlight.
- **Documents toolbar** is in `src/app/documents/page.tsx`. The "Edit Grid" dropdown uses local state (`showEditMenu`) with outside-click detection via `useEffect` + `mousedown` listener.
- **RTL layout:** The app uses Arabic (RTL) by default. Sidebar is on the right, toolbar flows right-to-left. Keep this in mind when clicking elements.
- **Translations:** UI labels are in `src/lib/translations.ts` with both `ar` and `en` sections. Check both if testing language switching.
- **Linting:** Run `cd BOB-2/frontend && npx eslint src/` to check for lint errors. Pre-existing warnings (mostly `no-explicit-any`) are expected.
- **Browser tooltips** use native `title` attribute, so hovering shows a tooltip after a short delay. Use `zoom` action on the tooltip area to capture it.

## Common Assertions

- Sidebar icons: Check for `<svg>` elements inside each `<a>` nav link
- Active state: The active nav item has amber/gold classes (`text-amber-400`, `border-amber-500/30`)
- Dropdown: When closed, submenu buttons are not in DOM. When open, they appear as child `<button>` elements
- Outside-click: Click anywhere on the spreadsheet grid to close dropdown; verify submenu buttons disappear from DOM

## Bank Reconciliation Testing

The dedicated `/bank-reconciliation` page is the primary reconciliation UI. To test it end-to-end, you need both frontend AND backend running locally:

```bash
# Terminal 1: Start backend
cd BOB-2/backend
pip install openpyxl  # if not installed
DATABASE_URL="sqlite:///./test_recon.db" SECRET_KEY="test-secret-key-for-local-dev-1234567890abcdef" APP_ENV="development" \
  python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# Terminal 2: Start frontend pointing to local backend
cd BOB-2/frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npx next dev -p 3000
```

### Key UI Elements — /bank-reconciliation page
- **Drop zone:** Drag-drop area with text "اسحب كشف البنك هنا أو اضغط للرفع" (AR) / "Drop bank statement here or click to upload" (EN)
- **Supported formats:** CSV, XLSX, XLS, PDF, Images, OFX, MT940
- **File info:** After upload, shows filename, size, extension, and green "صالح" (Valid) / red "غير مدعوم" (Unsupported) badge
- **Date range:** Optional From/To date inputs
- **Reconcile button:** "بدء التسوية" (AR) / "Start Reconciliation" (EN), disabled until valid file selected
- **10 Dashboard cards:** Statement Total, Ledger Total, Difference (color-coded: green < 0.01, yellow < 100, red >= 100), Statement Count, Ledger Count, Matched Count, AI Suggested Count, Bank Only Count, Odoo Only Count, Date Range Used
- **4 Tabbed tables:** Matched (مطابقة مؤكدة), AI Suggested (اقتراحات AI), Bank Only (كشف البنك فقط), Odoo Only (النظام فقط)
- **Export buttons:** "تصدير Excel" and "تصدير PDF" appear after results load
- **AI disclaimer:** Yellow banner "اقتراحات AI للمراجعة فقط — لا يتم اعتمادها تلقائياً" on AI tab

### File Upload via JavaScript
The page has a single hidden `<input type="file">` — use `querySelector` (not `querySelectorAll` with index):
```javascript
const content = `Date,Description,Amount\n2025-01-05,Salary,15000`;
const file = new File([content], 'test.csv', { type: 'text/csv' });
const input = document.querySelector('input[type="file"]');
const dt = new DataTransfer();
dt.items.add(file);
input.files = dt.files;
input.dispatchEvent(new Event('change', { bubbles: true }));
```

**Note:** Only one file (bank statement) is required to enable the reconcile button. The ledger data comes from Odoo.

### Results Structure — Tabbed Dashboard
- **10 summary cards** in 2 rows of 5, with accounting formatting (2 decimals) and color-coded values
- **4 separate tabs** each with count badge: مطابقة مؤكدة (1), اقتراحات AI (1), كشف البنك فقط (1), النظام فقط (1)
- **Matched tab:** 7-column table (Bank Date/Desc/Amount, Odoo Date/Desc/Amount, Match Type badge)
- **AI Suggested tab:** 8-column table (same as matched + Confidence %, Reason) with confidence badges
- **Bank Only / Odoo Only tabs:** 5-column tables (Date, Description, Amount, Row Number, Action badge)

### Testing Reconciliation UI Without LLM/Odoo
When no LLM provider or Odoo connection is available, use fetch intercept with mock data. **Critical:** The response MUST include ALL of these fields — the `/bank-reconciliation` page reads them for dashboard cards and will show incorrect data if any are missing:
```javascript
const nativeFetch = window.fetch;
window.fetch = function(url, options) {
  if (typeof url === 'string' && url.includes('bank-reconciliation')) {
    const mockData = {
      status: "success",
      statement_count: 5,
      statement_total: 25000.00,
      ledger_count: 4,
      ledger_total: 24500.00,
      difference: 500.00,
      odoo_raw_count: 4,
      date_range_used: { from: "2026-01-01", to: "2026-01-31" },
      matched: [
        {
          statement_txn: { date: "2026-01-05", description: "Salary Transfer", amount: 15000, row_number: 1 },
          ledger_txn: { date: "2026-01-05", description: "تحويل راتب", amount: 15000, row_number: 1 }
        }
      ],
      smart_matched: [
        {
          statement_txn: { date: "2026-01-10", description: "رسوم بنكية", amount: 150, row_number: 2 },
          ledger_txn: { date: "2026-01-12", description: "Bank Fees", amount: 200, row_number: 2 },
          confidence: 0.77, reason: "Vector DB similarity"
        }
      ],
      statement_only: [
        { date: "2026-01-15", description: "ATM Withdrawal", amount: -500, row_number: 3 }
      ],
      ledger_only: [
        { date: "2026-01-20", description: "قيد يدوي", amount: 350, row_number: 4 }
      ]
    };
    return Promise.resolve(new Response(JSON.stringify(mockData), {
      status: 200, headers: { 'Content-Type': 'application/json' }
    }));
  }
  return nativeFetch.apply(this, arguments);
};
```

### Confidence Badge Colors
- confidence >= 0.8: green (`bg-emerald-500/20 text-emerald-400 border-emerald-500/30`)
- confidence >= 0.6: yellow (`bg-yellow-500/20 text-yellow-400 border-yellow-500/30`)
- confidence < 0.6: red (`bg-red-500/20 text-red-400 border-red-500/30`)

### Testing Vector DB Matching (Backend Only, No UI)
For testing the Vector DB semantic matching logic without needing an Odoo connection or frontend:
```bash
# Clear ChromaDB state for clean test
rm -rf BOB-2/backend/storage/chroma_db

# Run direct Python test
cd BOB-2/backend
DATABASE_URL="sqlite:///./test_vector.db" SECRET_KEY="test-secret-key-for-local-dev-1234567890abcdef" \
  APP_ENV="development" python3 -c "
from app.erp.bank_reconciliation import reconcile
result = reconcile('/tmp/statement.csv', '/tmp/ledger.csv')
print(f'Smart matched: {len(result.smart_matched)}')
for sm in result.smart_matched:
    print(f'  {sm.statement_txn.description} <-> {sm.ledger_txn.description}: {sm.confidence} ({sm.reason})')
"
```

**Key insight:** Vector DB matching pairs transactions by semantic similarity (using BAAI/bge-m3 embeddings), NOT just by amount/date. To prove it works, use test CSVs with:
- Different languages (Arabic statement vs English ledger)
- Different amounts (to avoid rule-based matching taking precedence)
- Semantically similar descriptions ("رسوم بنكية" / "Bank Service Charges")

The ChromaDB `storage/chroma_db` directory should be cleared between test runs to avoid stale data from previous reconciliations affecting results.

### Port Conflicts
Port 3000 might be in use from a previous session. If you get `EADDRINUSE`, use a different port (e.g. `-p 3001`) or kill the process: `fuser -k 3000/tcp`.

### Backend API
`POST /api/v1/erp/bank-reconciliation` with multipart form: `statement=<file>`, optional `date_from`, `date_to`, `company_id` fields. Returns JSON with `status`, `statement_only`, `ledger_only`, `matched`, `smart_matched` arrays plus `statement_count`, `statement_total`, `ledger_count`, `ledger_total`, `difference`.

**Note:** The live API requires an active Odoo ERP connection (configured via `/erp` page). Without it, the API returns "لا يوجد اتصال نشط بنظام ERP". Use direct Python `reconcile()` calls for backend-only testing.

## Devin Secrets Needed

None required for frontend-only testing. The local dev server connects to the production backend without authentication.

For full-stack testing (Odoo/Telegram integration), the production backend needs:
- `TELEGRAM_BOT_TOKEN` (configured via Railway Variables on backend service)
- Odoo credentials (configured via the `/erp` page in the app UI)
