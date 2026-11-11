# PROJECT STATUS: Investor Intelligence

_Last updated: 2026-11-11_

## Summary

| Phase | Scope | Status |
|---|---|---|
| **1** | Mobile-first UI, PWA, bottom navigation, dashboard, search, SQLite, local authentication | ✅ **Done**: runs locally, tested |
| 2 | Company profiles, financial statements, historical data, market watchlists, charts | ⏳ Next |
| 3 | AI analyst (Ollama), PDF upload & analysis, research reports, bull/bear | Planned (Ollama status check already in place) |
| 4 | Screener, DCF, comparison, portfolio management, dividends | Partly started (transaction ledger with cost basis, realised P/L, dividends) |
| 5 | News, alerts, multi-user, backups, remote access | Partly started (invite-only multi-user, backups, export, remote-access guide) |

## Phase 1: what was delivered

**Mobile-first PWA (frontend/)**
- Designed for portrait phones (iPhone and Android): fixed bottom navigation (Home, Markets, Watchlist,
  AI Analyst, Portfolio), sticky top bar (logo, global search, notifications, profile), bottom sheets, no sidebars.
- Premium dark theme by default, optional light and auto themes. The choice is saved per device and per account,
  and a pre-paint script prevents a theme flash.
- Safe-area handling (`viewport-fit=cover`, `env(safe-area-inset-*)`), 16 px inputs (no iOS zoom), touch
  feedback, reduced-motion support, tabular numbers.
- Web app manifest, icons (any and maskable), Apple touch icon, 8 iOS splash screens, hand-written service worker:
  - cache-first for immutable assets, network-first for pages and API;
  - offline: previously loaded data is served from cache, and the UI shows **"You are offline. Showing data saved &lt;time&gt;"**;
  - per-user API cache is cleared on sign-in and sign-out.
- Global search (from every screen): your holdings, watchlists, notes, and SEC-registered companies.
- Screens: Home dashboard, Markets (browse by exchange), Company page, Watchlists (multiple, with private
  notes), Portfolio (transactions → positions), AI Analyst (live Ollama status and setup), Notes, Settings
  (theme, currency, password, signed-in devices, data export), Administration (invites, members, SEC sync,
  backups), Data sources.

**Backend (backend/)**
- FastAPI + SQLite (WAL mode, foreign keys). Decimals are stored exactly (no floating point for money).
- Invite-only accounts, Argon2id password hashing, server-side sessions (only token hashes stored),
  HttpOnly SameSite=Lax cookies, CSRF header check, login and registration rate limits, sign out other devices,
  admin can disable accounts.
- Every user-owned table is filtered by the authenticated user. Isolation is covered by tests.
- SEC EDGAR company list sync (one request, declared User-Agent, at most once per hour, delisted tickers flagged
  rather than deleted, failures recorded and shown).
- Portfolio ledger (average-cost method): rejects oversells and future dates, handles multiple currencies
  without FX conversion, allows non-US symbols.
- Notifications (invite used, data sync completed), preferences, dashboard, system status, JSON export,
  consistent SQLite backups.
- CLI: `create-admin`, `create-invite`, `sync-sec`, `backup`.

**Verification performed**
- `pytest`: 21 tests pass (auth, CSRF, rate limiting, invites, user isolation, SEC parse/sync/error handling,
  search ranking, LIKE escaping, ledger maths, backups, export).
- `eslint` and `tsc` clean; `next build` produces a static export.
- End-to-end walkthrough in a headless iPhone 14 Pro and Pixel 7 profile against the real server: login → search →
  company → add to watchlist → markets → create portfolio → record transaction (with European decimal comma) →
  AI status → admin invite → light theme → **offline reload shows cached portfolio with timestamp**.

### Honest limitations of Phase 1
- **No prices, fundamentals or charts yet.** The UI says so explicitly. Nothing is estimated or invented.
- The SEC sync could not be exercised against the live SEC server from the development sandbox (network
  blocked there). It is tested against the documented file format with a mocked transport. Run
  `python -m app.cli sync-sec` once on your machine to confirm.
- Rate limits are in-memory (reset on restart; single process).
- Schema migrations: tables are created automatically. Alembic (free) will be added before the first
  schema change that needs migrating existing data.
- PWA install and offline mode require HTTPS on phones (see README → Tailscale).

---

## ZERO-COST ARCHITECTURE

**Rule:** nothing in this project may require payment, a credit card or a subscription to work.
Optional integrations must say so and must degrade gracefully when absent. No paid dependency is added silently.

### A. Software dependencies (all bundled, all free)

| Dependency | Purpose | Free? | Credit card? | Usage limits? | Subscription? | Licence / open-source alternative |
|---|---|---|---|---|---|---|
| Python, FastAPI, Uvicorn, Pydantic | API server | Yes | No | No | No | PSF / MIT / BSD (is open source) |
| SQLAlchemy + SQLite | Database | Yes | No | No | No | MIT / public domain |
| argon2-cffi | Password hashing | Yes | No | No | No | MIT |
| httpx | HTTP client (SEC, Ollama) | Yes | No | No | No | BSD |
| pytest | Tests | Yes | No | No | No | MIT |
| Node.js, Next.js, React | Frontend | Yes | No | No | No | MIT |
| Tailwind CSS | Styling | Yes | No | No | No | MIT |
| shadcn/ui pattern + Radix UI | UI components (copied into repo, not a service) | Yes | No | No | No | MIT |
| lucide-react | Icons | Yes | No | No | No | ISC |
| SWR | Data fetching | Yes | No | No | No | MIT |
| Geist font (npm `geist`) | Typography, bundled locally (no Google Fonts call) | Yes | No | No | No | SIL OFL 1.1 |
| clsx, tailwind-merge, class-variance-authority | Utilities | Yes | No | No | No | MIT / Apache-2.0 |
| Playwright (dev only, optional) | Generating icons / e2e checks | Yes | No | No | No | Apache-2.0 |
| **Planned:** TradingView Lightweight Charts | Price charts (Phase 2) | Yes | No | No | No | Apache-2.0 (attribution link required by its licence) |
| **Planned:** Recharts | Financial charts (Phase 2) | Yes | No | No | No | MIT |
| **Planned:** Ollama + open models | Local AI (Phase 3) | Yes | No | Hardware only | No | MIT (Ollama); model licences vary (e.g. Llama community licence, Qwen Apache-2.0); check per model |
| **Planned:** PyMuPDF | PDF parsing (Phase 3) | Yes | No | No | No | **AGPL-3.0** (free; fine for private self-hosting. A commercial licence is only needed for closed-source distribution). Alternative: `pypdf` (BSD) |

### B. Infrastructure

| Item | Choice | Free? | Credit card? | Limits? | Subscription? | Open-source alternative |
|---|---|---|---|---|---|---|
| Hosting | Your own computer / home server | Yes | No | Your hardware | No | n/a |
| Database | SQLite file | Yes | No | No | No | is open source |
| Authentication | Built in (Argon2id + sessions) | Yes | No | No | No | is open source |
| E-mail | **Not used** (invite codes are shared manually) | n/a | n/a | n/a | n/a | n/a |
| Remote access | Tailscale Personal (optional) | Yes (non-commercial) | No | User and device caps; check current plan | No | **Headscale** or plain **WireGuard** (fully open source) |
| HTTPS | `tailscale serve` (Let's Encrypt) or Caddy | Yes | No | Let's Encrypt rate limits (generous) | No | Caddy (Apache-2.0) |

### C. Data providers

Rules: official and free sources first. Never bypass rate limits or terms. Show the source and timestamp
next to every figure. Never present delayed data as real-time. Never invent missing figures.

| Provider | Status | Free? | Card? | Rate / quota limits | Coverage | History | Terms / attribution |
|---|---|---|---|---|---|---|---|
| **SEC EDGAR**: `company_tickers_exchange.json` | ✅ **In use** | Yes, no key | No | ≤ 10 requests/second per user; must send a User-Agent with a contact e-mail. We make **1 request per sync, ≤ 1 per hour** | US SEC registrants (~10k tickers, incl. exchange) | Current snapshot | US public-domain government data; follow the SEC fair-access policy |
| SEC EDGAR: XBRL `companyfacts` / `submissions` | Phase 2 (planned) | Yes, no key | No | Same 10 req/s policy | US filers' reported financials, filing index | Varies by company (XBRL from ~2009) | Same as above |
| **ECB Data Portal** (SDMX API) | Phase 2 (planned) | Yes, no key | No | No published hard quota; we will cache and throttle | Euro-area rates, FX reference rates, macro | Decades | Free reuse with source attribution (ECB statistics reuse policy) |
| **FRED** (St. Louis Fed) | Phase 2 (optional) | Yes, free API key | No | Per-key request limits apply (verify current figure in FRED docs before enabling) | US macro | Decades | Some series are third-party copyrighted. Attribution is required, and the terms must be checked per series |
| Company IR sites / annual reports | Phase 3 (manual PDF upload) | Yes | No | n/a | Any company | Whatever is published | Users upload documents they are entitled to read |
| Free RSS news feeds | Phase 5 (planned) | Usually | No | Respect each feed's terms and caching | Varies | Short | Headlines and links only, with attribution |
| **Stooq** | Phase 2 (optional, under review) | Free | No | Now requires a (free) key obtained via CAPTCHA, with a low daily hit quota ("Exceeded the daily hits limit") | Global EOD prices | Long | Terms unclear for programmatic use. **Will not be enabled until terms are confirmed.** End-of-day only, never real-time |
| Alpha Vantage | Optional only | Free tier | No | Reported 25 requests/day (free tier). Far too low for watchlists | US / global | Long | Non-commercial free tier; attribution per terms |
| Finnhub | Optional only | Free tier | No | Reported ~60 calls/minute; some endpoints premium-only | US-centric | Limited on free | Free tier excludes many endpoints |
| Financial Modeling Prep | Optional only | Free tier | No | Daily cap on free tier (figure not verified; check pricing page) | Mostly US on free | Limited | Many endpoints are paid-only |
| EODHD | Optional only | Free tier | No | Very small daily cap on the free tier (verify) | Global | 1 year on free (verify) | Paid for real use |

> Free-tier limits of commercial providers change often. The figures above come from third-party
> summaries and **must be re-verified on each provider's pricing page** before an integration is enabled.
> None of them is a mandatory dependency, and the app works fully without them.

**Market prices: current decision.** Phase 1 shows **no prices**. For Phase 2 the plan is end-of-day
prices from a source whose terms permit this use, clearly labelled with date and "end of day". If no
such free source is acceptable, prices stay optional and the app continues without them.

### D. AI

| Item | Choice | Free? | Card? | Limits | Subscription? | Notes |
|---|---|---|---|---|---|---|
| Inference | **Ollama**, local | Yes | No | Your CPU/GPU/RAM (≈8 GB RAM for 7–8B models) | No | No Claude/OpenAI key required |
| Models | Llama 3.x, Qwen 2.5, Mistral, etc. | Yes | No | Hardware | No | Check each model's licence |
| Embeddings / RAG | Ollama embedding model + SQLite (Phase 3) | Yes | No | Hardware | No | No external vector DB |

If Ollama is not running, the app shows a clear "AI is unavailable" message and all non-AI features keep working.

### E. Features that cannot be guaranteed free (marked optional)

| Feature | Limitation | Plan |
|---|---|---|
| Real-time quotes | No genuinely free, licence-clean real-time feed exists | Not offered. End-of-day or delayed data is labelled with its timestamp |
| Broad fundamentals outside the US | No free official equivalent of SEC XBRL for all EU issuers | Manual PDF upload + local AI extraction (Phase 3). ESEF filings to be investigated |
| Push notifications to phones | Web Push itself is free (VAPID), but needs HTTPS and iOS 16.4+ home-screen install | Phase 5, optional |

---

## Next steps (Phase 2)
1. SEC XBRL company facts → income statement, balance sheet and cash-flow tabs on the company page (with source and as-of dates).
2. Historical financials stored in SQLite, with refresh and provenance per figure.
3. Decide on an end-of-day price source after verifying terms. Lightweight Charts for price history.
4. ECB FX reference rates for optional portfolio currency conversion (always labelled with the rate date).
