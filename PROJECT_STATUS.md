# PROJECT STATUS: Investor Intelligence

_Last updated: 2026-11-11 (Phase 3)_

## Summary

| Phase | Scope | Status |
|---|---|---|
| **1** | Mobile-first UI, PWA, bottom navigation, dashboard, search, SQLite, local authentication | ✅ **Done**: runs locally, tested |
| **2** | Company profiles, financial statements, historical data, market watchlists, charts | ✅ **Done**: tested with fixtures; live sources still to confirm on your machine |
| **3** | AI analyst (Ollama), PDF upload & analysis, research reports, bull/bear | ✅ **Done**: tested with a mocked Ollama; run with a real model on your machine |
| 4 | Screener, DCF, comparison, portfolio management, dividends | ⏳ Next. Partly started (ledger, cost basis, realised P/L, dividends, market value at stored close) |
| 5 | News, alerts, multi-user, backups, remote access | Partly started (invite-only multi-user, backups, export, remote-access guide) |

## Phase 3: what was delivered

**AI Analyst tab** (mobile chat):
- Streaming answers from a **local Ollama model**, with conversation history and follow-up questions.
  Follow-ups automatically reuse the previous turn's companies and documents.
- Task templates: Ask · Company analysis · Bull & bear case · Earnings analysis · Financial statement
  analysis · Valuation explained · Compare companies (2–3) · Investment thesis · Portfolio analysis ·
  Document analysis. Shortcuts on every company page ("AI analysis", "Bull vs bear").
- Context chips: pick up to 3 companies and any of your PDFs. Model settings sheet: chat model, embedding
  model and temperature, per user.
- **Save as thesis**: stores the answer in Notes, linked to the company, with model name, date, sources and
  any unverified numbers in a footer.
- When Ollama is not running, the tab shows exactly what to install. **Every other feature keeps working**
  (tested).

**Documents** (`/documents`, also in the profile menu): private PDF upload (≤ 25 MB, ≤ 600 pages). Text
extraction with PyMuPDF on your server, chunking with page numbers, keyword index (SQLite FTS5/BM25), and
semantic index (local Ollama embeddings, if an embedding model is installed). Retrieval merges both
(reciprocal-rank fusion). Scanned PDFs without text are rejected with an explanation (no OCR service).

**How answers stay grounded** (`backend/app/services/analyst.py`):
1. The model receives **numbered sources** built by the app:
   - `[S]` SEC profile;
   - `[F]` SEC statements (annual, plus quarterly where relevant);
   - `[C]` app-calculated ratios and multiples (P/E and market capitalisation only when a stored price exists);
   - `[P]` stored end-of-day price with date;
   - `[D]` PDF passages with page;
   - `[N]` your own notes, labelled as opinion;
   - `[H]` your holdings.

   Missing data is stated explicitly (e.g. "No stored price… do not state a share price").
2. A strict system prompt: use only the sources, cite them, never call prices real-time, and always use the
   sections **Verified data / Calculations / Assumptions / Opinion**.
3. **Number check after every answer:** each number in the answer is compared with the source values
   (handling thousands separators, %, ×, million/billion). Numbers under "Verified data" that are not found
   in the sources are flagged in yellow. New numbers in calculations, assumptions or opinion are listed
   separately. The app also reports whether the model followed the required structure.
4. Tap any citation chip to see exactly what the model was given (including the PDF passage).

**Model abstraction:** `services/llm.py` defines an `LLMProvider` interface (`list_models`, `chat_stream`,
`embed`). Ollama is the implementation; other local servers can be added without touching the rest.
At most 2 generations run at once to protect the host machine.

**Privacy:** conversations, documents and AI settings are per user. Other members get 404 for them (tested).
PDFs are stored under `backend/data/documents/<user>/` and never leave your machine. The personal JSON export
now includes AI conversations and the document list.

**Verification performed**
- `pytest`: **41 tests pass**, including 9 new Phase 3 tests:
  - AI unavailable → clear 503 while the rest of the app works;
  - model selection and fallback;
  - PDF upload, page extraction, indexing, rejection of non-PDF and scanned files, deletion, and other users blocked;
  - hybrid search finds the right page;
  - grounded chat: sources sent, prompt rules, SSE stream, follow-up inheritance, saving a note with provenance;
  - task validation and conversation isolation;
  - missing price and financials stated in the prompt;
  - portfolio context;
  - unit handling in the number check.
- End-to-end on a headless iPhone 14 Pro against a stand-in Ollama server: PDF upload and indexing, company →
  AI analysis, streaming answer with sections, table and citations, the number-check panel, the sources sheet with
  PDF passage, save as thesis, conversation history, and the AI-offline state.

### Phase 3: honest limitations
- **Not run against a real model in the build sandbox** (no Ollama or model download possible there). The
  stand-in server only proves the plumbing. Answer quality depends on the model you install: 7–8B models
  (llama3.1:8b, qwen2.5:7b) follow the section format reasonably well but can still make mistakes, which is why
  the number check exists. Bigger models (14B+) are better if your hardware allows.
- The number check confirms that a figure **appears** in the sources. It cannot confirm the figure is attributed
  to the right line or year, and it cannot verify arithmetic. Always read the cited source for important decisions.
- Local inference is slow on CPUs (tens of seconds per answer). The first request also loads the model into memory.
- No OCR for scanned PDFs. Tables in PDFs are extracted as plain text, so complex tables may lose structure.
- Backups: the SQLite backup does **not** include the PDF files in `backend/data/documents/`. Back up that
  folder too.

## Phase 2: what was delivered

**Company research page** (`/company?t=TICKER`), with tabs for vertical scrolling on a phone:
- **Overview:** latest stored end-of-day close (always labelled "end of day, not live" with its date),
  an interactive price chart (TradingView Lightweight Charts, line/OHLC, 1M–MAX),
  key figures for the latest fiscal year, and the SEC company profile (SIC industry, fiscal year end,
  incorporation, address, former names).
- **Financials:** Income, Balance sheet, Cash flow and Ratios, annual (up to 10 years) and quarterly (up to 12
  quarters). There is a Recharts bar chart of any row (tap a row label) and a horizontally scrollable table with a sticky
  first column. **Tap any value** to see its provenance: XBRL concept, form, filing date, accession number,
  a link to the filing, and whether it was *reported* or *calculated* (with the formula).
- **Filings:** 10-K/10-Q/8-K/20-F… list with filters, linking to the documents on sec.gov.
- **Notes:** the user's private notes for that company.

**Data integrity rules implemented** (`backend/app/services/fundamentals.py`):
- Values are stored exactly as filed. When a period was reported more than once (restatements), the most
  recently filed value wins and its filing is cited.
- Standardised line items map to an ordered list of US-GAAP **and IFRS** concepts (so 20-F/40-F filers
  are covered). The concept actually used is shown per value.
- Quarterly values: a directly reported 3-month value is used when it exists. Otherwise the value is
  *calculated* from year-to-date figures (e.g. Q4 = 12 months − 9 months), marked with a "c" and its formula.
  Non-additive items (EPS, share counts) are **never** derived this way.
- Ratios (margins, growth, FCF, ROE, current ratio, debt/equity) are always marked calculated. ROE is not
  shown for quarters because that would need annualising, which is an assumption.
- Missing = "—". Nothing is estimated.

**Historical data storage (SQLite):** `company_profiles`, `filings`, `financial_facts` (every used fact with
provenance), `price_bars`, `fx_rates`, `fetch_states` (freshness/errors per company), and `provider_usage`
(request budget).
SEC data is fetched on the first visit to a company, refreshed at most daily (manual refresh: at most every 10 min),
and spaced to ≤ 5 requests/s. Errors are shown in the UI next to the last stored data.

**Prices (end of day only):**
- **CSV import** (Administration → End-of-day prices): any daily file with `Date` and `Close` columns
  (comma or semicolon, decimal commas accepted). The admin must name the source, and every bar is labelled with it.
- **Tiingo (optional)**: only when `II_TIINGO_API_KEY` is set. Each ticker is refreshed at most every 12 h,
  under a self-imposed budget of 40 requests/hour and 400/day (configurable). The budget is stored in the database.
- Watchlists and Home show the last close, its date and the change vs the previous stored close.
- Portfolio shows market value and unrealised P/L **only** when a stored price exists in the same currency
  as the position. Currency totals appear only when *every* open position in that currency is priced.

**Markets:** ECB euro reference rates (14 currencies) with a history chart per currency, plus the existing
SEC securities browser.

**Verification performed**
- `pytest`: **32 tests pass**, including 11 new Phase 2 tests:
  - parsing, restatement and concept fallback;
  - quarterly derivation, with EPS not derived;
  - balance sheet and ratio maths;
  - filings filter and URLs;
  - SEC error surfaced (not hidden);
  - CSV import, including the admin-only restriction;
  - quotes, and portfolio valuation that refuses mixed currencies or partial totals;
  - Tiingo auth, caching and the hourly budget;
  - ECB parsing, skipping empty observations.
- `eslint`, `tsc` and `next build` are clean.
- End-to-end in a headless iPhone 14 Pro: company overview with chart, annual and quarterly statements, the provenance
  sheet, ratios, filings, watchlist quotes, the FX card and history, portfolio market value, admin price import,
  and the light theme.

### Phase 2: honest limitations
- **Live sources not exercised from the build sandbox.** data.sec.gov, the ECB API and Tiingo were network-blocked there.
  All parsing is tested against the **documented formats** with synthetic fixtures (`backend/tests/fixtures.py`,
  fictional "Example Corp"). On first run on your machine, open a large company (e.g. AAPL) and compare a few
  figures with its latest 10-K. Please report any mismatch.
- XBRL coverage varies: some companies use custom extension concepts, so a line can legitimately be "—".
- Fiscal periods are labelled by **period end date** (e.g. "FY · Sep 2024"), not by the company's own
  fiscal-year naming, to avoid ambiguity.
- Price history exists only for tickers you import or that the optional provider covers. Without either,
  the app says "No price history stored".
- Tiingo's free plan is licensed for internal/personal use. Sharing its prices with friends is a grey area,
  so it is off by default; CSV import of data you are entitled to use is the conservative option.

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
| TradingView Lightweight Charts | Price charts | Yes | No | No | No | Apache-2.0 (attribution logo kept on, as its licence requires) |
| Recharts | Financial and FX charts | Yes | No | No | No | MIT |
| Ollama + open models | Local AI analyst | Yes | No | Hardware only | No | MIT (Ollama); model licences vary (e.g. Llama community licence, Qwen Apache-2.0); check per model |
| PyMuPDF | PDF text extraction | Yes | No | No | No | **AGPL-3.0** (free; fine for private self-hosting of this unmodified-for-distribution app. A commercial licence is only needed for closed-source distribution). Alternative: `pypdf` (BSD) |
| numpy | Vector similarity for document search | Yes | No | No | No | BSD |
| python-multipart | File uploads | Yes | No | No | No | Apache-2.0 |
| react-markdown + remark-gfm | Rendering AI answers (raw HTML disabled) | Yes | No | No | No | MIT |

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
| **SEC EDGAR**: XBRL `companyfacts` / `submissions` | ✅ **In use** | Yes, no key | No | Same 10 req/s policy. We space requests to ≤ 5/s and refresh each company at most daily | US-GAAP and IFRS filers' reported financials, filing index | Varies by company (XBRL from ~2009) | Same as above |
| **ECB Data Portal** (EXR) | ✅ **In use** | Yes, no key | No | No published hard quota; we refresh at most every 6 h (one request) | Euro FX reference rates (14 currencies) | We store the last 30 fixings plus accumulated history | Free reuse with source attribution (ECB statistics reuse policy) |
| **CSV price import** | ✅ **In use** | Yes | No | None | Whatever you import | Whatever you import | Only import data you are entitled to use; source label required |
| **Tiingo** (EOD prices) | ✅ Optional, off by default | Free plan (account, no card) | No | Free plan limited per hour/day (verify current figures). We cap at 40/h and 400/day and refresh a ticker at most every 12 h | US equities/ETFs EOD | Long | Free plan licensed for internal/personal use; check before sharing with others |
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

**Market prices: current decision (Phase 2).** End-of-day only, always labelled with date and source.
Default: CSV import. Optional: Tiingo free plan with a strict request budget. No real-time data anywhere.
Stooq remains disabled until its terms for programmatic use are clear.

### D. AI

| Item | Choice | Free? | Card? | Limits | Subscription? | Notes |
|---|---|---|---|---|---|---|
| Inference | **Ollama**, local | Yes | No | Your CPU/GPU/RAM (≈8 GB RAM for 7–8B models) | No | No Claude/OpenAI key required |
| Models | Llama 3.x, Qwen 2.5, Mistral, etc. | Yes | No | Hardware | No | Check each model's licence |
| Embeddings / RAG | Ollama embedding model (e.g. nomic-embed-text) + SQLite FTS5 + numpy | Yes | No | Hardware | No | No external vector DB; keyword search works without any embedding model |

If Ollama is not running, the app shows a clear "AI is unavailable" message and all non-AI features keep working.

### E. Features that cannot be guaranteed free (marked optional)

| Feature | Limitation | Plan |
|---|---|---|
| Real-time quotes | No genuinely free, licence-clean real-time feed exists | Not offered. End-of-day or delayed data is labelled with its timestamp |
| Broad fundamentals outside the US | No free official equivalent of SEC XBRL for all EU issuers | Manual PDF upload + local AI extraction (Phase 3). ESEF filings to be investigated |
| Push notifications to phones | Web Push itself is free (VAPID), but needs HTTPS and iOS 16.4+ home-screen install | Phase 5, optional |

---

## Next steps (Phase 4)
1. Stock screener over stored SEC fundamentals (growth, margins, leverage, FCF), honest about coverage.
2. DCF valuation tool: inputs from SEC data, every assumption user-editable and labelled, sensitivity table.
3. Company comparison view (side-by-side statements and ratios, charts).
4. Portfolio management: allocation charts, performance over time from stored closes, optional ECB FX conversion
   (always labelled with the rate date).
5. Dividend tracking: dividend calendar and income per year from recorded transactions.
