# Investor Intelligence

A private investment research app that **lives on your phone**. It is a web app you add to the
Home Screen: no server, no account, no subscription. Your data is stored only on the device, in the
browser (IndexedDB), and works offline.

- **What it does today:** portfolios (transactions, broker CSV import, average-cost P/L, allocation,
  time-weighted and money-weighted returns, dividends), watchlists, research notes, end-of-day prices
  imported from CSV, exchange rates (typed in or downloaded from the ECB), backup and restore.
- **Cost:** €0. The app's files are hosted for free on GitHub Pages; nothing runs on a server.
- **Stack:** Next.js 16 static export, React 19, TypeScript, Tailwind CSS 4, Radix UI, Recharts,
  decimal.js for exact money maths. A hand-written service worker makes it work offline.

> Plan, decisions and the cost audit: [PROJECT_STATUS.md](PROJECT_STATUS.md).

---

## 1. Use it on the iPhone

1. Open the GitHub Pages address in **Safari**: `https://<your-github-user>.github.io/<repository>/`.
2. Tap **Share → Add to Home Screen**.
3. Always open the app from that icon. On iOS, a Home Screen web app keeps its data separately from
   Safari, so data entered in a Safari tab is not visible in the installed app (and vice versa).

**Back up regularly:** Menu → Settings & backup → **Export backup**, then *Save to Files* (e.g. iCloud
Drive). If you clear Safari's website data, delete the app or change phone, only a backup brings the data back
(**Restore from backup…**). The Home screen reminds you when your last backup is older than 14 days.

### Getting your data in

- **Transactions:** Portfolio → Import CSV (header row; comma or semicolon; decimal commas accepted;
  all rows or nothing). Example:
  ```
  Date;Symbol;Type;Quantity;Price;Fees;Currency
  2024-01-02;ASML.AS;Buy;2;600,50;1,50;EUR
  2024-03-01;ASML.AS;Dividend;0;3,20;0;EUR
  ```
- **Prices:** Menu → Prices & exchange rates → Import (a CSV with at least `Date` and `Close`). Prices are
  end-of-day closes and always shown with their date; nothing is real-time.
- **Exchange rates:** only needed for a portfolio total in your base currency. Type them in
  (1 EUR = x), or tap *Download latest ECB rates* (works only if the ECB allows direct browser access;
  otherwise the app says so).

## 2. Publish it (one time, free)

The repository includes a GitHub Actions workflow (`.github/workflows/pages.yml`) that tests, builds and
publishes the app on every push to `main`.

1. GitHub → repository **Settings → General → Danger zone → Change visibility → Public**
   (GitHub Pages is free for public repositories). The repository contains code only, never your data.
2. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
3. Push to `main` (or run the workflow from the **Actions** tab). The address appears in the workflow run.

## 3. Develop

```bash
cd frontend
npm ci
npm run dev        # http://localhost:3000
npm test           # unit tests (portfolio maths, CSV import, storage, backup)
npm run build      # static site in frontend/out
```

To preview the GitHub Pages build locally: `NEXT_PUBLIC_BASE_PATH=/investments npm run build`, then serve
`out/` under `/investments/`.

## 4. Project layout

```
frontend/
  src/app/(app)/          pages: home, watchlist, portfolio, notes, prices, settings
  src/lib/local/          on-device "API": IndexedDB storage, portfolio maths, CSV parsing, backup, ECB
  src/components/         UI, charts, app shell
  public/sw.js            offline support
.github/workflows/        GitHub Pages deployment
```
