---
name: testing-guardianai-frontend
description: Test GuardianAI frontend UI changes end-to-end. Use when verifying sidebar, toolbar, documents page, or ERP page UI changes.
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

The `/team` page has a bank reconciliation section (second icon row below accountant row). To test it end-to-end, you need both frontend AND backend running locally:

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
- **Second pill:** "ارفق كشف دفتر البنك" (bank ledger upload)
- **Third pill:** "إجراء المطابقة البنكية" (reconcile button, disabled until both files uploaded)
- **Title:** "محاسب البنك" (cyan/blue gradient, left of pills)

### File Upload via JavaScript
The upload pills trigger hidden `<input type="file">` elements which open native file dialogs. To set files programmatically:
```javascript
const content = `Date,Description,Amount\n2025-01-05,Salary,15000`;
const file = new File([content], 'test.csv', { type: 'text/csv' });
const input = document.querySelectorAll('input[type="file"]')[1]; // index 1 = statement, 2 = ledger
const dt = new DataTransfer();
dt.items.add(file);
input.files = dt.files;
input.dispatchEvent(new Event('change', { bubbles: true }));
```

### Clearing Files
The × buttons on pills are very small. Use JavaScript to click them reliably:
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

### Testing Reconciliation UI Without LLM
When no LLM provider (Ollama/Grok) is available, `smart_matched` will be empty. To test the UI rendering, intercept the fetch API to return mock data. **Important:** `matched` uses `MatchedPair` format with `statement_txn` and `ledger_txn` (not flat transactions):
```javascript
const originalFetch = window.fetch;
window.fetch = function(url, options) {
  if (typeof url === 'string' && url.includes('bank-reconciliation')) {
    const mockData = {
      status: "success",
      statement_only: [{ date: "2025-01-25", description: "رسوم بنكية", amount: 150, row_number: 5 }],
      ledger_only: [{ date: "2025-01-28", description: "Bank Service Charge", amount: 200, row_number: 6 }],
      matched: [
        {
          statement_txn: { date: "2025-01-15", description: "تحويل راتب محمد", amount: 15000, row_number: 1 },
          ledger_txn: { date: "2025-01-14", description: "Salary Transfer - Mohammed", amount: 15000, row_number: 7 }
        }
      ],
      smart_matched: [
        {
          statement_txn: { date: "2025-01-22", description: "دفعة مورد أحمد", amount: 7500, row_number: 3 },
          ledger_txn: { date: "2025-01-23", description: "Vendor Payment - Ahmed", amount: 7500, row_number: 9 },
          confidence: 0.85, reason: "Similar vendor name"
        }
      ],
      statement_total: 22650, ledger_total: 22700, difference: -50,
      statement_count: 3, ledger_count: 3
    };
    return Promise.resolve(new Response(JSON.stringify(mockData), {
      status: 200, headers: { 'Content-Type': 'application/json' }
    }));
  }
  return originalFetch.apply(this, arguments);
};
```
Use **different descriptions** for `statement_txn` vs `ledger_txn` in matched pairs to verify both columns display independently. This also lets you test confidence badge colors (≥0.8 green, ≥0.6 yellow, <0.6 orange).

### Port Conflicts
Port 3000 might be in use from a previous session. If you get `EADDRINUSE`, use a different port (e.g. `-p 3001`) or kill the process: `fuser -k 3000/tcp`.

### Backend API
`POST /api/v1/erp/bank-reconciliation` with multipart form: `statement=<file>`, optional `date_from` and `date_to` fields. Returns JSON with `statement_only`, `ledger_only`, `matched`, `smart_matched` arrays plus totals.

## Devin Secrets Needed

None required for frontend-only testing. The local dev server connects to the production backend without authentication.

For full-stack testing (Odoo/Telegram integration), the production backend needs:
- `TELEGRAM_BOT_TOKEN` (configured via Railway Variables on backend service)
- Odoo credentials (configured via the `/erp` page in the app UI)