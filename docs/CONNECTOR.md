# Claude connector (ask Claude on your phone about your data)

The connector lets the **Claude apps** (iPhone/Android, web, desktop) use your Investor Intelligence data as a
*custom connector*: portfolios, watchlists, notes, alerts, the PDFs you uploaded, and the company data stored in
the app. You ask in the Claude app; Claude calls the app's tools and answers from your data.

- **Cost:** no API key and no pay-per-use. It runs on your Claude plan (custom connectors are available on Free
  — one connector — Pro, Max, Team and Enterprise). Tailscale Funnel is part of Tailscale's free Personal plan.
- **Privacy:** what Claude reads through the connector is sent to Anthropic to answer you. The local AI Analyst
  (Ollama) keeps working as before and sends nothing out.
- **Access:** each person signs in with their own app username and password and only sees their own data
  (plus notes others chose to share). Revoke a connection any time in **Settings → Claude connector**.

## How it works

```
Claude app (iPhone) ──► Anthropic servers ──HTTPS──► Tailscale Funnel :8443 ──► 127.0.0.1:8001 connector
                                                                               (MCP + OAuth only)
Your devices on the tailnet ──► Tailscale Serve :443 ──► 127.0.0.1:8000 full app (stays private)
```

Claude's servers must reach the connector over the public internet, so it runs as a **separate process** that
serves only `/mcp`, `/oauth/*` and `/.well-known/*`. The UI and `/api` are never exposed by it.

Security measures: OAuth 2.1 with PKCE (S256) and dynamic client registration, redirects accepted only to
`https://claude.ai/api/mcp/auth_callback` (and `claude.com`), short-lived access tokens (60 min), rotating
refresh tokens (30 days), tokens stored only as SHA-256 hashes, the same failed-login rate limits as the app,
and every tool runs with the signed-in user's permissions. Use a strong password: the sign-in page is public.

## Setup on the Mac mini (after the main app works)

1. **Enable Funnel** for your tailnet: Tailscale admin console → *Access controls* → add the `funnel` node
   attribute (the console offers it the first time you run the command below), and *DNS* → enable HTTPS
   certificates (already done if `tailscale serve` works).

2. **Expose the connector port publicly** (8443 is one of the ports Funnel allows: 443, 8443, 10000):
   ```bash
   tailscale funnel --bg --https=8443 http://127.0.0.1:8001
   tailscale funnel status        # shows https://<mac>.<tailnet>.ts.net:8443 (Funnel on)
   ```
   Your existing `tailscale serve` on 443 stays tailnet-only.

3. **Configure** `backend/.env` (same file as the app):
   ```
   II_CONNECTOR_PUBLIC_URL=https://<mac>.<tailnet>.ts.net:8443
   ```
   Restart the app so Settings shows the connector URL:
   `sudo launchctl kickstart -k system/com.investorintelligence.app`

4. **Run the connector as a service** (starts at boot, no user needs to be logged in):
   ```bash
   sudo tee /Library/LaunchDaemons/com.investorintelligence.connector.plist >/dev/null <<'PLIST'
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0"><dict>
     <key>Label</key><string>com.investorintelligence.connector</string>
     <key>UserName</key><string>YOURNAME</string>
     <key>ProgramArguments</key><array><string>/bin/bash</string><string>-lc</string>
       <string>cd /Users/YOURNAME/investments && ./run-connector.sh</string></array>
     <key>EnvironmentVariables</key><dict>
       <key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
       <key>HOME</key><string>/Users/YOURNAME</string></dict>
     <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
     <key>StandardOutPath</key><string>/tmp/investor-connector.log</string>
     <key>StandardErrorPath</key><string>/tmp/investor-connector.log</string>
   </dict></plist>
   PLIST
   sudo launchctl bootstrap system /Library/LaunchDaemons/com.investorintelligence.connector.plist
   ```
   Replace `YOURNAME` with your macOS short user name. Check: open
   `https://<mac>.<tailnet>.ts.net:8443/health` from your phone with Wi-Fi **and** Tailscale off — it must answer
   `{"status":"ok","configured":true}`.

5. **Add it to Claude.** Custom connectors are added in Claude on the web or desktop app (once) and then
   appear in the iPhone app too:
   Claude → **Customize → Connectors → Add → Add custom connector** → name `Investor Intelligence`, URL
   `https://<mac>.<tailnet>.ts.net:8443/mcp` → **Add** → **Connect** → sign in with your app username and
   password → **Allow**.

6. **Use it on the iPhone:** in a chat, tap **+ → Connectors** and make sure *Investor Intelligence* is on, then ask,
   e.g. *"Using my documents, what did the 2024 annual report say about the dividend policy?"* or
   *"How is my Core portfolio doing this year?"*

## Tools Claude gets

| Tool | What it does |
|---|---|
| `list_documents`, `search_documents`, `read_document` | Your uploaded PDFs (search passages with page numbers, read up to 10 pages) |
| `get_portfolios`, `get_portfolio_performance` | Holdings, cost basis, P/L, TWR / XIRR, dividends |
| `get_watchlists`, `get_notes`, `get_alerts`, `get_news` | Your lists, notes (and shared notes), alerts, headlines and filings |
| `search_securities`, `get_company`, `get_financials`, `get_price_history`, `compare_companies`, `get_valuations` | Company data stored in the app (SEC/ESEF filings, end-of-day prices) |
| `save_note` | Saves a private note — only tool that writes; disable with `II_CONNECTOR_WRITE_TOOLS=false` |

In Claude you can also set each tool to *Always allow*, *Ask* or *Blocked* (Customize → Connectors → Investor
Intelligence).

## Turning it off

`tailscale funnel --https=8443 off`, then
`sudo launchctl bootout system/com.investorintelligence.connector` and remove `II_CONNECTOR_PUBLIC_URL`.
Revoke existing connections in Settings → Claude connector.

## Troubleshooting

- **"Couldn't reach the MCP server" in Claude:** the URL must work from outside your tailnet (step 4 check).
  `tailscale funnel status` must show Funnel *on* for 8443.
- **Sign-in page says "Unknown client":** remove the connector in Claude and add it again.
- **Logs:** `tail -50 /tmp/investor-connector.log`.
