"use client";

import Link from "next/link";
import useSWR from "swr";
import { Briefcase, ChevronRight, Database, Eye, FileText, Search, Sparkles } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorNote, SourceLine } from "@/components/page";
import { QuoteCell, SecurityRow } from "@/components/security-row";
import { useAuth } from "@/components/providers";
import { useShell } from "@/components/shell/app-shell";
import { fmtInt, fmtMoney, fmtRelative } from "@/lib/format";
import type { Dashboard, NewsEntry, SystemStatus } from "@/lib/types";

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

function Stat({ label, value, href }: { label: string; value: string; href: string }) {
  return (
    <Link href={href} className="rounded-2xl border border-border/60 bg-card px-3.5 py-3 active:scale-[0.98]">
      <p className="num text-[22px] font-semibold leading-tight">{value}</p>
      <p className="text-[12px] text-muted-foreground">{label}</p>
    </Link>
  );
}

export default function HomePage() {
  const { user } = useAuth();
  const { openSearch } = useShell();
  const { data, error } = useSWR<Dashboard>("/api/dashboard");
  const { data: status } = useSWR<SystemStatus>("/api/system/status", { refreshInterval: 120_000 });
  const { data: news } = useSWR<{ items: NewsEntry[] }>("/api/news?scope=mine&limit=4");
  const sec = data?.data_sources.find((s) => s.source === "sec_company_tickers_exchange");

  return (
    <div>
      <p className="text-[13px] text-muted-foreground">
        {new Intl.DateTimeFormat(undefined, { weekday: "long", day: "numeric", month: "long" }).format(new Date())}
      </p>
      <h1 className="text-[28px] font-bold tracking-tight">
        {greeting()}, {user?.display_name.split(" ")[0]}
      </h1>

      <ErrorNote error={error} />

      {!data ? (
        <div className="mt-4 grid grid-cols-3 gap-2">
          <Skeleton className="h-[68px]" />
          <Skeleton className="h-[68px]" />
          <Skeleton className="h-[68px]" />
        </div>
      ) : (
        <div className="mt-4 grid grid-cols-3 gap-2">
          <Stat label="Watching" value={fmtInt(data.watched_securities)} href="/watchlist" />
          <Stat label="Portfolios" value={fmtInt(data.portfolios.length)} href="/portfolio" />
          <Stat label="Notes" value={fmtInt(data.note_count)} href="/notes" />
        </div>
      )}

      {data && data.securities_available === 0 && (
        <Card className="mt-4 border-warning/40 bg-warning/5">
          <CardContent className="pt-4">
            <p className="font-semibold">Company list not loaded yet</p>
            <p className="mt-1 text-[13px] text-muted-foreground">
              Search and watchlists use the official SEC EDGAR company list.{" "}
              {user?.role === "admin" ? (
                <>
                  Load it from{" "}
                  <Link href="/admin" className="font-medium text-primary">
                    Administration
                  </Link>
                  .
                </>
              ) : (
                "Ask the administrator to sync it."
              )}
            </p>
          </CardContent>
        </Card>
      )}

      <button
        onClick={openSearch}
        className="mt-4 flex w-full items-center gap-3 rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 px-4 py-3.5 text-left ring-1 ring-primary/20 active:scale-[0.99]"
      >
        <Search className="size-5 text-primary" />
        <span className="flex-1">
          <span className="block font-semibold">Research a company</span>
          <span className="block text-[13px] text-muted-foreground">
            {data ? `${fmtInt(data.securities_available)} SEC-registered securities` : "Search by ticker or name"}
          </span>
        </span>
        <ChevronRight className="size-4 text-muted-foreground" />
      </button>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Watchlist</CardTitle>
          <Link href="/watchlist" className="text-[13px] font-medium text-primary">
            See all
          </Link>
        </CardHeader>
        {data?.watch_items.length ? (
          <ul className="divide-y divide-border/60 pb-1">
            {data.watch_items.slice(0, 6).map((i) => (
              <li key={`${i.watchlist_id}-${i.security.id}`}>
                <SecurityRow security={i.security} sub={i.note || i.security.name} quote={<QuoteCell quote={i.quote} />} />
              </li>
            ))}
          </ul>
        ) : (
          <CardContent className="flex items-center gap-3 text-[13px] text-muted-foreground">
            <Eye className="size-5 shrink-0" />
            {data ? "Nothing on your watchlist yet. Search for a company and tap “Watch”." : <Skeleton className="h-10 w-full" />}
          </CardContent>
        )}
        <CardContent className="pt-0">
          <SourceLine>End-of-day closes with their date. Never real-time.</SourceLine>
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Portfolios</CardTitle>
          <Link href="/portfolio" className="text-[13px] font-medium text-primary">
            Open
          </Link>
        </CardHeader>
        <CardContent>
          {data?.portfolios.length ? (
            <ul className="space-y-2">
              {data.portfolios.map((p) => (
                <li key={p.id}>
                  <Link href={`/portfolio?id=${p.id}`} className="flex items-center gap-3 rounded-xl bg-elevated px-3 py-2.5 active:scale-[0.99]">
                    <Briefcase className="size-4 text-muted-foreground" />
                    <span className="flex-1">
                      <span className="block font-medium">{p.name}</span>
                      <span className="text-[12px] text-muted-foreground">
                        {p.error ? <span className="text-negative">{p.error}</span> : `${p.open_positions} open positions`}
                      </span>
                    </span>
                    <span className="num text-right text-[13px]">
                      {Object.entries(p.cost_basis_by_currency).map(([ccy, v]) => (
                        <span key={ccy} className="block">
                          {fmtMoney(v, ccy, true)}
                        </span>
                      ))}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[13px] text-muted-foreground">{data ? "No portfolio yet. Record your transactions to track cost basis." : ""}</p>
          )}
          <SourceLine>Amounts are cost basis calculated from your own transactions. Open a portfolio for market value.</SourceLine>
        </CardContent>
      </Card>

      {!!news?.items.length && (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle>Latest for your companies</CardTitle>
            <Link href="/news" className="text-[13px] font-medium text-primary">
              News
            </Link>
          </CardHeader>
          <ul className="divide-y divide-border/60 pb-1">
            {news.items.map((n, i) => (
              <li key={i}>
                <a href={n.link || undefined} target="_blank" rel="noreferrer noopener" className="block px-4 py-2.5 active:bg-muted">
                  <span className="block truncate text-[14px] font-medium">{n.title}</span>
                  <span className="text-[11px] text-muted-foreground">
                    {n.source} · {fmtRelative(n.date)}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {!!data?.recent_notes.length && (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle>Recent notes</CardTitle>
            <Link href="/notes" className="text-[13px] font-medium text-primary">
              All notes
            </Link>
          </CardHeader>
          <ul className="divide-y divide-border/60 pb-1">
            {data.recent_notes.map((n) => (
              <li key={n.id}>
                <Link href={`/notes?id=${n.id}`} className="flex items-center gap-3 px-4 py-3 active:bg-muted">
                  <FileText className="size-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate font-medium">{n.title}</span>
                  <span className="text-[12px] text-muted-foreground">{fmtRelative(n.updated_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>System</CardTitle>
          <Link href="/sources" className="text-[13px] font-medium text-primary">
            Details
          </Link>
        </CardHeader>
        <CardContent className="space-y-2.5">
          <div className="flex items-center gap-3">
            <Database className="size-4 text-muted-foreground" />
            <span className="flex-1 text-[14px]">SEC company list</span>
            {sec?.status === "ok" ? (
              <Badge variant="positive">Synced {fmtRelative(sec.last_success_at)}</Badge>
            ) : sec?.status === "error" ? (
              <Badge variant="negative">Sync failed</Badge>
            ) : (
              <Badge variant="muted">Not synced</Badge>
            )}
          </div>
          <div className="flex items-center gap-3">
            <Sparkles className="size-4 text-muted-foreground" />
            <span className="flex-1 text-[14px]">Local AI (Ollama)</span>
            {!status ? (
              <Skeleton className="h-4 w-16" />
            ) : status.ai.available ? (
              <Badge variant="positive">{status.ai.models.length} models</Badge>
            ) : (
              <Badge variant="muted">Offline</Badge>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
