"use client";

import Link from "next/link";
import useSWR from "swr";
import { Briefcase, ChevronRight, Eye, FileText, HardDriveDownload, ShieldCheck } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorNote, SourceLine } from "@/components/page";
import { QuoteCell, SecurityRow } from "@/components/security-row";
import { fmtInt, fmtMoney, fmtRelative } from "@/lib/format";
import type { Dashboard, Preferences } from "@/lib/types";
import { cn } from "@/lib/utils";

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

function BackupCard({ last, due }: { last: string | null; due: boolean }) {
  return (
    <Link
      href="/settings#backup"
      className={cn(
        "mt-4 flex items-center gap-3 rounded-2xl px-4 py-3.5 ring-1 active:scale-[0.99]",
        due ? "bg-warning/10 ring-warning/40" : "bg-card ring-border/60",
      )}
    >
      {due ? <HardDriveDownload className="size-5 shrink-0 text-warning" /> : <ShieldCheck className="size-5 shrink-0 text-positive" />}
      <span className="flex-1">
        <span className="block font-semibold">{due ? "Back up your data" : "Data on this device"}</span>
        <span className="block text-[13px] text-muted-foreground">
          {last ? `Last backup ${fmtRelative(last)}.` : "No backup yet."} Everything is stored only in this browser on this phone.
        </span>
      </span>
      <ChevronRight className="size-4 text-muted-foreground" />
    </Link>
  );
}

export default function HomePage() {
  const { data, error } = useSWR<Dashboard>("/api/dashboard");
  const { data: prefs } = useSWR<Preferences>("/api/preferences");
  const name = prefs?.display_name?.split(" ")[0];

  return (
    <div>
      <p className="text-[13px] text-muted-foreground">
        {new Intl.DateTimeFormat(undefined, { weekday: "long", day: "numeric", month: "long" }).format(new Date())}
      </p>
      <h1 className="text-[28px] font-bold tracking-tight">
        {greeting()}
        {name ? `, ${name}` : ""}
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

      {data && <BackupCard last={data.last_backup_at} due={data.backup_due} />}

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
              <li key={`${i.watchlist_id}-${i.security.ticker}`}>
                <SecurityRow security={i.security} sub={i.note || i.security.name} quote={<QuoteCell quote={i.quote} />} />
              </li>
            ))}
          </ul>
        ) : (
          <CardContent className="flex items-center gap-3 text-[13px] text-muted-foreground">
            <Eye className="size-5 shrink-0" />
            {data ? "Nothing on your watchlist yet. Open Watchlist and tap +." : <Skeleton className="h-10 w-full" />}
          </CardContent>
        )}
        <CardContent className="pt-0">
          <SourceLine>End-of-day closes you imported, with their date. Never real-time.</SourceLine>
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
            <p className="text-[13px] text-muted-foreground">{data ? "No portfolio yet. Record your transactions or import your broker's CSV." : ""}</p>
          )}
          <SourceLine>Amounts are cost basis calculated from your own transactions. Open a portfolio for market value.</SourceLine>
        </CardContent>
      </Card>

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
    </div>
  );
}
