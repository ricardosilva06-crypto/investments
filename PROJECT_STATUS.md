# PROJECT STATUS: Investor Intelligence

_Last updated: 2026-11-11 (phone-only app, delivery 1 of 3)_

## Decision: everything on the phone

The owner decided that the app should not depend on any computer or server. It is now a **static web app**
added to the iPhone Home Screen. All data is stored **on the device** (IndexedDB) and the app works offline.
The previous server version (FastAPI + SQLite, SEC/ESEF sync, Ollama AI, Claude connector) was **deleted**
at the owner's request; it remains in the git history.

Consequences accepted by the owner:

- No automatic data: no SEC EDGAR sync, no news, no alerts or push notifications, no scheduled jobs.
  Prices and company figures are imported by the user.
- Single user, single device. Data survives only through the app's own backup file.
- Claude is used through the owner's own Claude app (Projects / attachments) with a file exported by the app,
  not through an API key (no pay-per-use).

## Delivery plan

| Delivery | Scope | Status |
|---|---|---|
| **1** | On-device storage; portfolios (transactions, broker CSV import, average cost, P/L, allocation, TWR, XIRR, dividends); watchlists; notes; price CSV import; exchange rates (manual or ECB download); backup export/restore; GitHub Pages deployment | ✅ **Done** |
| **2** | PDF documents read on the phone (text extraction + OCR for scans), search in documents; **"Claude" tab** that exports a "For Claude" file (portfolio, notes, watchlists, figures) for a Claude Project; backups including PDFs | Planned |
| **3** | Companies from imported data: ESEF annual reports (EU) parsed on the phone, financial statements and ratios, DCF calculator, company comparison | Planned |

### Delivery 1: what was delivered

- **On-device "API"** (`frontend/src/lib/local/`): the pages still call `/api/...` paths, answered in the
  browser from IndexedDB. Writes that affect the ledger are atomic (a sell beyond holdings, or a delete that would
  cause one, is refused; CSV imports are all-or-nothing).
- **Portfolio maths ported from the server version** with exact decimals (decimal.js): average-cost ledger,
  market value at the latest imported close (same currency only; never converted silently), allocation with
  optional base currency, daily value history (a day is valued only if every holding has a close within 7 days),
  daily-linked TWR, XIRR, dividends (TTM, by year, yield on cost). The server's hand-checked return tests were
  ported and pass.
- **Watchlists** accept any ticker (there is no reference list on the device); names and exchange are editable.
- **Prices & exchange rates** page: CSV import with source label, chart of stored closes, delete; exchange rates
  "1 EUR = x" typed in or downloaded from the ECB data API.
- **Backup**: one JSON file via the iOS share sheet ("Save to Files") or a download; validated on restore
  (app, version, required fields) and restored all-or-nothing after confirmation; reminder on Home after 14 days.
  The app asks the browser for persistent storage and shows usage in Settings.
- **Offline**: service worker caches the app; verified by reloading the installed pages offline.
- **Tests**: 12 unit tests (`npm test`) for ledger, CSV import, returns, allocation/FX, watchlists, notes,
  search and backup round-trip; end-to-end run on an emulated iPhone 13 (add security, import prices, record a
  transaction, check market value, notes, export, wipe, restore, offline reload) with no console errors.

### Delivery 1: honest limitations

- **ECB download not verified from a phone.** It depends on the ECB allowing direct browser requests (CORS).
  If it does not, the app shows a clear message and rates can be typed in.
- **Data loss risk**: clearing Safari website data, deleting the Home Screen app or changing phone removes the
  data; only the backup file protects it. On iOS the installed app and Safari tabs have separate storage.
- **Making the repository public** exposes the code and its commit history (including commit author names and
  e-mail addresses). No secrets were found in the history. The user's data is never in the repository.
- Prices are whatever the user imports: end-of-day, labelled with date and source, never real-time.
- Not yet tested on a physical iPhone (emulated iPhone in Chromium only).

## ZERO-COST ARCHITECTURE

| Item | Choice | Free? | Credit card? | Limits | Subscription? | Open-source alternative |
|---|---|---|---|---|---|---|
| Hosting of the app files | GitHub Pages (public repository) | Yes | No | Soft limits (site ≤ 1 GB, ~100 GB/month bandwidth) far above this app | No | Any static host; the `out/` folder is plain files |
| Build & deploy | GitHub Actions | Yes (public repos) | No | Generous minutes for public repos | No | Build locally with `npm run build` |
| Database | IndexedDB in the browser | Yes | No | Device storage quota | No | n/a (built into the browser) |
| Authentication | None (single user, data never leaves the device) | n/a | n/a | n/a | n/a | n/a |
| Market data | User CSV imports | Yes | No | None | No | n/a |
| Exchange rates | ECB data API (optional) or manual entry | Yes, no key | No | No published hard quota; one request per tap | No | Manual entry |
| AI | Owner's existing Claude app plan, via exported files (delivery 2) | Uses the existing plan | No new card | Plan limits | Only the plan the owner already has | n/a |
| Libraries | Next.js, React, Tailwind, Radix UI, Recharts, decimal.js, lucide | Yes (MIT/ISC/Apache-2.0) | No | No | No | They are open source |

No paid service is used. No API key is needed.
