# Investor Intelligence

A private, mobile-first investment research app (PWA) that runs on **your own computer**
and costs **€0** in mandatory subscriptions, hosting, APIs or AI fees.

- **Frontend:** Next.js 16 + React 19 + TypeScript + Tailwind CSS 4, shadcn/ui-style components (Radix UI), exported as static files.
- **Backend:** Python FastAPI + SQLite (one file, easy to back up).
- **AI:** Ollama with open-source models, running locally. Answers are grounded in the app's data and your PDFs,
  with citations, and every number is checked against the sources.
- **Data:** official, free sources first: SEC EDGAR (company list, XBRL financial statements, filings),
  ECB euro reference rates, and end-of-day prices via CSV import or the optional Tiingo free plan.
- **Charts:** TradingView Lightweight Charts (prices) and Recharts (financials, FX).

> Status and the full cost audit live in [PROJECT_STATUS.md](PROJECT_STATUS.md) (see **ZERO-COST ARCHITECTURE**).

---

## 1. Run it locally (one process)

Requirements: Python 3.11+, Node.js 20+ (both free).

```bash
cp backend/.env.example backend/.env      # then put your e-mail in II_SEC_USER_AGENT
./run.sh                                   # installs deps, builds the PWA, serves on :8000
```

In a second terminal, create the first (admin) account and load the company list:

```bash
cd backend
.venv/bin/python -m app.cli create-admin          # asks for username + password
.venv/bin/python -m app.cli sync-sec              # one request to SEC EDGAR (~10k US companies)
```

Financial statements are downloaded from SEC EDGAR the first time someone opens a company,
then refreshed at most daily. The **screener** needs a one-time download (Screener page → "Download from SEC",
16 requests) and can be refreshed from the same page.

**Prices (optional):** the app never invents prices. Either import a daily CSV in
**Administration → End-of-day prices** (columns `Date,Close`, optionally `Open,High,Low,Volume`), or
create a free Tiingo account and set `II_TIINGO_API_KEY` in `backend/.env` (see PROJECT_STATUS.md for its terms).

Open `http://localhost:8000` on the computer, or `http://<computer-LAN-IP>:8000` on a phone
on the same Wi-Fi. (To install the app on a phone and use it offline, you need HTTPS. See section 3.)

### Development mode (hot reload)

```bash
# terminal 1
cd backend && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --reload --port 8000
# terminal 2
cd frontend && npm install && npm run dev        # http://localhost:3000 (proxies /api to :8000)
```

Tests and checks:

```bash
cd backend && .venv/bin/python -m pytest -q
cd frontend && npm run lint && npm run typecheck && npm run build
```

### Local AI analyst (optional, free)

```bash
# on the computer that runs the app — https://ollama.com (open source)
ollama pull llama3.1:8b          # or qwen2.5:7b; bigger models are better if you have the RAM
ollama pull nomic-embed-text     # optional: semantic search in your PDFs
```

The AI Analyst tab detects Ollama automatically (default `http://127.0.0.1:11434`). Without it, the app
works normally and explains how to enable AI.

### Automatic jobs

The server refreshes news feeds (30 min), ECB rates (6 h), SEC data, optional prices and alerts for every watched or
held company (daily, 22:00 UTC), and makes a backup (03:00 UTC). The computer must be on at those times; missed jobs
run at the next start. You can see them and run them manually in **Administration → Scheduled jobs**.

## 2. Inviting friends

Accounts are **invite-only**. As admin: open the profile menu → **Administration** → **Invites** →
**Create**, then share the single-use code (valid 7 days). Your friend opens `/register` and enters it.
You can also run `python -m app.cli create-invite --label "Alex"`.

Each member's watchlists, portfolios, notes, alerts, documents, AI conversations, valuations, notifications and
preferences are private. A note is visible to other members only if its owner ticks **Share with members**
(read-only). Every API query
is filtered by the signed-in user, and tests check this isolation (`backend/tests/test_data.py`).

**Be aware:** whoever runs the server can read the SQLite file, and admin backups contain everyone's data.
Only invite people who trust the host.

## 3. Phone access and HTTPS (free options)

iOS and Android only enable **Install app** and **offline mode** (service workers) on HTTPS
(or `localhost`). Recommended free setups, from safest to least safe:

| Option | Cost | What it does | Exposure |
|---|---|---|---|
| **Tailscale** (+ `tailscale serve`) | Free *Personal* plan (non-commercial; 6 users at the time of writing, check current terms). No card needed | Private WireGuard network between your devices and friends'. `tailscale serve --bg 8000` gives a real HTTPS URL (`https://<machine>.<tailnet>.ts.net`) | Not reachable from the internet |
| **Headscale** + Tailscale apps | Free, open source (self-hosted control server) | Same as above without depending on Tailscale's servers | You run an extra service |
| **WireGuard** (plain) | Free, open source | VPN into your home network; use Caddy with an internal CA for HTTPS (install its root cert on each phone) | Needs a router port forward (UDP) |
| Cloudflare Tunnel / port forwarding | Free tiers exist | Puts the app on the public internet | **Not recommended**: see below |

With Tailscale:

```bash
tailscale serve --bg 8000          # HTTPS -> http://127.0.0.1:8000
# in backend/.env
II_COOKIE_SECURE=true
```

Friends can join your tailnet, or you can share just this machine with them (Tailscale "node sharing").
Then they open the `https://…ts.net` URL and use **Share → Add to Home Screen** (iOS) or **Install app** (Android).

### Security implications of internet exposure

If you ever expose the app publicly (port forwarding, tunnels), then:

- Anyone can reach the login page. Passwords are hashed with Argon2id, and login and registration are
  rate-limited, but that only slows attackers down. Use long, unique passwords.
- Always use HTTPS with `II_COOKIE_SECURE=true`.
- Keep the OS, Python and Node dependencies updated, and run the server as a non-admin user.
- The FastAPI docs at `/api/docs` are reachable. Consider blocking `/api/docs` at your reverse proxy.
- Rate limits are in-memory and per process. Put a reverse proxy in front if you need more protection.

A private network (Tailscale or WireGuard) avoids all of this, which is why it's the default recommendation.

### Hardening checklist (also checked in Administration → Security & remote access)

1. HTTPS via `tailscale serve --bg 8000` (or Caddy), then `II_COOKIE_SECURE=true`.
2. `II_ALLOWED_HOSTS=<your-machine>.<tailnet>.ts.net,localhost` (rejects requests for other host names).
3. Keep `II_API_DOCS=false` (the default).
4. One or two admin accounts at most. Members get invites with the member role.
5. Run the server as a normal user, keep OS, Python and Node updated, and keep `backend/data/` readable only by that user.
6. Keep backups somewhere else, encrypted.

### Notifications on your phone

Open **Alerts → Push notifications → Turn on** on each device (needs HTTPS; on iPhone, first add the app to the
home screen). Alerts always also appear in the bell menu.

## 4. Backups

- A **nightly backup** runs automatically (03:00 UTC). **Administration → Backups → Create backup now** makes one
  on demand. Each backup is a zip in `backend/data/backups/` with a consistent database snapshot **and all uploaded
  PDFs**. The 14 most recent are kept (`II_BACKUPS_KEEP`).
- CLI and cron: `cd backend && .venv/bin/python -m app.cli backup`
- Each user can download their own data as JSON in **Settings → Export my data**.
- Uploaded PDFs live in `backend/data/documents/` and are included in the backup zip.
- **Restore:** stop the server, unzip the backup, copy `investor.db` to `backend/data/investor.db` and the
  `documents/` folder to `backend/data/documents/`, then start the server.
- Backups contain everyone's data and are not encrypted by the app: keep them on an encrypted disk.

## 5. Project layout

```
backend/
  app/main.py            FastAPI app, CSRF + security headers, serves the static PWA
  app/models.py          SQLite schema (SQLAlchemy 2)
  app/routers/           auth, securities/search, companies (profile/financials/filings/prices/fx), research (screener/compare/DCF),
                         engage (news, alerts, push, jobs, security check),
                         watchlists, notes, portfolios (+ analytics, CSV import), account, admin, ai
  app/services/          sec + sec_client (EDGAR), fundamentals (XBRL statements), prices (CSV/Tiingo), ecb (FX),
                         llm (model abstraction, Ollama), documents (PDF + RAG), analyst (grounding + number check),
                         screener (SEC frames), valuation (DCF), portfolio ledger + analytics, news (RSS/Atom),
                         alerts, push (Web Push), scheduler, backup (zip with DB + PDFs)
  app/cli.py             create-admin, create-invite, sync-sec, backup
  tests/                 pytest suite (auth, isolation, ledger, sync, backups)
frontend/
  src/app/(app)/         Home, Markets, Watchlist, AI Analyst, Portfolio, Company, Notes, Settings, Admin, Sources
  src/app/(auth)/        Login, Register (invite)
  src/components/shell/  Top bar, bottom navigation, global search, notifications, account menu
  public/sw.js           Service worker (offline cache with "saved at" timestamps)
  public/manifest.webmanifest, icons/, splash/
```
