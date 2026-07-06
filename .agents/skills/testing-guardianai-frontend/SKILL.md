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
| `/team` | Team Management | User list, roles, bank reconciliation |
| `/documents` | Documents / Spreadsheet | Toolbar, grid, AI assistant |
| `/audit` | Audit Control Room | Account fetching, attachments |
| `/erp` | ERP Connections | Odoo setup, Telegram bot config |
| `/erp/discovery` | ERP Discovery | Company info from Odoo |

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

The `/team` page has a bank reconciliation section. To test it end-to-end, you need both frontend AND backend running locally:

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

### Key UI Elements (RTL layout — pills flow right-to-left)
- **First pill (rightmost):** "ارفق كشف البنك" (bank statement upload, accepts .csv/.xlsx/.xls)
- **Second pill:** "نطاق التاريخ" (date range selector)
- **Third pill:** "إجراء المطابقة البنكية" (reconcile button, disabled until file uploaded)
- **Title:** "محاسب البنك" (cyan/blue gradient, left of pills)

### File Upload via JavaScript
The upload pills trigger hidden `<input type="file">` elements. The bank statement input is at index [1]:
```javascript
const content = `Date,Description,Amount\n2025-01-05,Salary,15000`;
const file = new File([content], 'test.csv', { type: 'text/csv' });
const input = document.querySelectorAll('input[type="file"]')[1]; // index 1 = bank statement
const dt = new DataTransfer();
dt.items.add(file);
input.files = dt.files;
input.dispatchEvent(new Event('change', { bubbles: true }));
```

**Note:** Only one file (bank statement) is required to enable the reconcile button. The ledger data comes from Odoo.

### Clearing Files
The x buttons on pills are very small. Use JavaScript to click them reliably:
```javascript
document.querySelectorAll('button').forEach(btn => {
  if (btn.textContent === '×') btn.click();
});
```

### Results Modal Structure — Unified Table
- **Summary cards (5 columns):** statement count/total, ledger count/total, matched count, 🤖 AI count, difference (red if non-zero)
- **Single unified table** with 5 columns: التاريخ | كشف البنك (متطابق) | النظام (متطابق) | كشف البنك فقط | النظام فقط
- All transaction types merged and sorted by date ascending
- **Matched rows (green):** both Bank and System columns filled with independent data from `statement_txn` and `ledger_txn`
- **Smart matched rows (purple tint):** same as matched but with purple amounts and confidence badge (🤖 XX%)
- **Bank-only rows (red):** only "كشف البنك فقط" column filled, others show "—"
- **System-only rows (amber):** only "النظام فقط" column filled, others show "—"
- **Close button:** "إغلاق" at top-left of modal

### Testing Reconciliation UI Without LLM/Odoo
When no LLM provider or Odoo connection is available, use fetch intercept with mock data. **Critical:** The response MUST include ALL of these fields (frontend calls `.toFixed(2)` on numeric fields and will crash with `TypeError: Cannot read properties of undefined` if missing):
```javascript
const nativeFetch = window.fetch;
window.fetch = function(url, options) {
  if (typeof url === 'string' && url.includes('bank-reconciliation')) {
    const mockData = {
      status: "success",                    // REQUIRED: triggers setReconResults
      statement_count: 5,                   // REQUIRED: displayed in summary card
      statement_total: 24000.00,            // REQUIRED: .toFixed(2) called on this
      ledger_count: 5,                      // REQUIRED: displayed in summary card
      ledger_total: 24050.00,               // REQUIRED: .toFixed(2) called on this
      difference: 50.00,                    // REQUIRED: .toFixed(2) called on this
      matched: [
        {
          statement_txn: { date: "2025-01-15", description: "تحويل راتب محمد", amount: 15000, row_number: 1 },
          ledger_txn: { date: "2025-01-14", description: "Salary Transfer Mohammed", amount: 15000, row_number: 7 },
          reason: "تطابق المبلغ والتاريخ"
        }
      ],
      smart_matched: [
        {
          statement_txn: { date: "2025-01-25", description: "رسوم بنكية شهرية", amount: 150, row_number: 5 },
          ledger_txn: { date: "2025-01-28", description: "Bank Service Charges", amount: 200, row_number: 5 },
          confidence: 0.77, reason: "Vector DB similarity=0.77"
        }
      ],
      statement_only: [
        { date: "2025-01-22", description: "شراء أدوات مكتبية", amount: 350, row_number: 4 }
      ],
      ledger_only: []
    };
    return Promise.resolve(new Response(JSON.stringify(mockData), {
      status: 200, headers: { 'Content-Type': 'application/json' }
    }));
  }
  return nativeFetch.apply(this, arguments);
};
```

### Confidence Badge Colors
- confidence >= 0.8: green (`bg-green-500/20 text-green-400`)
- confidence >= 0.6: yellow (`bg-yellow-500/20 text-yellow-400`)
- confidence < 0.6: orange (`bg-orange-500/20 text-orange-400`)

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
