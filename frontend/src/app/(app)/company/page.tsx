"use client";

import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { ChevronDown, ExternalLink, Eye, FileText, NotebookPen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorNote, SourceLine } from "@/components/page";
import { TickerAvatar } from "@/components/security-row";
import { AddToWatchlistSheet } from "@/components/add-to-watchlist";
import { fmtDate, fmtRelative } from "@/lib/format";
import type { Note, Security } from "@/lib/types";
import { cn } from "@/lib/utils";

type Detail = { security: Security; edgar_url: string | null; watchlist_ids: number[]; note_count: number };

function Expandable({ title, icon: Icon, defaultOpen = false, children }: { title: string; icon: React.ElementType; defaultOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = React.useState(defaultOpen);
  return (
    <section className="overflow-hidden rounded-2xl border border-border/60 bg-card">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-center gap-3 px-4 py-3.5 text-left">
        <Icon className="size-[18px] text-muted-foreground" />
        <span className="flex-1 font-semibold">{title}</span>
        <ChevronDown className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      {open && <div className="border-t border-border/60 px-4 py-3">{children}</div>}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-xl bg-elevated px-3 py-2.5">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="num mt-0.5 truncate font-semibold">{value}</p>
    </div>
  );
}

export default function CompanyPage() {
  const t = (useSearchParams().get("t") ?? "").toUpperCase();
  const { data, error, mutate } = useSWR<Detail>(t ? `/api/securities/${encodeURIComponent(t)}` : null);
  const { data: notes } = useSWR<Note[]>(t ? `/api/notes?ticker=${encodeURIComponent(t)}` : null);
  const [watchOpen, setWatchOpen] = React.useState(false);

  if (!t) return <ErrorNote error="No ticker given." />;
  if (error) return <ErrorNote error={error} />;
  if (!data)
    return (
      <div className="space-y-3">
        <Skeleton className="h-16" />
        <Skeleton className="h-24" />
        <Skeleton className="h-12" />
      </div>
    );

  const s = data.security;
  const watching = data.watchlist_ids.length > 0;
  return (
    <div>
      <div className="flex items-center gap-3">
        <TickerAvatar ticker={s.ticker} />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight">{s.ticker}</h1>
            {s.exchange && <Badge variant="muted">{s.exchange}</Badge>}
            {!s.is_listed && <Badge variant="warning">Not in latest SEC list</Badge>}
          </div>
          <p className="truncate text-[14px] text-muted-foreground">{s.name}</p>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2">
        <Button variant={watching ? "secondary" : "default"} onClick={() => setWatchOpen(true)}>
          <Eye /> {watching ? `Watching (${data.watchlist_ids.length})` : "Watch"}
        </Button>
        <Button variant="secondary" asChild>
          <Link href={`/notes?new=1&t=${encodeURIComponent(s.ticker)}`}>
            <NotebookPen /> Add note
          </Link>
        </Button>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2">
        <Metric label="Ticker" value={s.ticker} />
        <Metric label="Exchange" value={s.exchange ?? "—"} />
        <Metric label="SEC CIK" value={s.cik ?? "—"} />
      </div>
      <SourceLine>
        Identity data from SEC EDGAR, updated {fmtDate(s.updated_at, true)}. Prices, fundamentals and charts are not shown until a
        verified free source is connected (Phase 2). Nothing on this page is estimated.
      </SourceLine>

      <div className="mt-5 space-y-3">
        <Expandable title={`Your notes${notes?.length ? ` (${notes.length})` : ""}`} icon={FileText} defaultOpen>
          {notes?.length ? (
            <ul className="space-y-2">
              {notes.map((n) => (
                <li key={n.id}>
                  <Link href={`/notes?id=${n.id}`} className="block rounded-xl bg-elevated px-3 py-2.5 active:scale-[0.99]">
                    <span className="block font-medium">{n.title}</span>
                    <span className="line-clamp-2 text-[13px] text-muted-foreground">{n.body || "No content"}</span>
                    <span className="text-[11px] text-muted-foreground">Edited {fmtRelative(n.updated_at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[13px] text-muted-foreground">No private notes on {s.ticker} yet.</p>
          )}
        </Expandable>

        <Expandable title="Official filings" icon={ExternalLink}>
          {data.edgar_url ? (
            <a href={data.edgar_url} target="_blank" rel="noreferrer" className="flex items-center justify-between rounded-xl bg-elevated px-3 py-3 font-medium active:scale-[0.99]">
              Open {s.ticker} filings on SEC EDGAR <ExternalLink className="size-4 text-muted-foreground" />
            </a>
          ) : (
            <p className="text-[13px] text-muted-foreground">No SEC CIK available.</p>
          )}
          <p className="mt-2 text-[12px] text-muted-foreground">10-K, 10-Q and 8-K filings at the source. In-app financial statements arrive in Phase 2.</p>
        </Expandable>

      </div>

      <AddToWatchlistSheet ticker={s.ticker} open={watchOpen} onOpenChange={setWatchOpen} onChanged={() => mutate()} />
    </div>
  );
}
