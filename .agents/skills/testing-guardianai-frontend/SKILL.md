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
| `/team` | Team Management | User list, roles |
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

## Devin Secrets Needed

None required for frontend-only testing. The local dev server connects to the production backend without authentication.

For full-stack testing (Odoo/Telegram integration), the production backend needs:
- `TELEGRAM_BOT_TOKEN` (configured via Railway Variables on backend service)
- Odoo credentials (configured via the `/erp` page in the app UI)
