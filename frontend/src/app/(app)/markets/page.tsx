"use client";

import * as React from "react";
import useSWR from "swr";
import useSWRInfinite from "swr/infinite";
import { Building2, Loader2, Plus, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorNote, PageHeader, SourceLine } from "@/components/page";
import { SecurityRow } from "@/components/security-row";
import { AddToWatchlistSheet } from "@/components/add-to-watchlist";
import { FxCard } from "@/components/fx-card";
import { fmtDate, fmtInt } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Security } from "@/lib/types";

type Page = { items: Security[]; total: number; source: string; source_url: string; last_success_at: string | null };
const PAGE = 40;

export default function MarketsPage() {
  const [exchange, setExchange] = React.useState<string | null>(null);
  const [q, setQ] = React.useState("");
  const [dq, setDq] = React.useState("");
  const [adding, setAdding] = React.useState<string | null>(null);
  React.useEffect(() => {
    const t = setTimeout(() => setDq(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  const { data: exchanges } = useSWR<{ exchange: string; count: number }[]>("/api/securities/exchanges");
  const key = (i: number, prev: Page | null) => {
    if (prev && prev.items.length < PAGE) return null;
    const p = new URLSearchParams({ limit: String(PAGE), offset: String(i * PAGE) });
    if (dq) p.set("q", dq);
    if (exchange) p.set("exchange", exchange);
    return `/api/securities?${p}`;
  };
  const { data, error, size, setSize, isValidating } = useSWRInfinite<Page>(key);
  const items = data?.flatMap((p) => p.items) ?? [];
  const meta = data?.[0];
  const more = !!data && data[data.length - 1].items.length === PAGE;

  return (
    <div>
      <PageHeader title="Markets" subtitle="Reference rates and SEC-registered securities" />

      <div className="mb-4">
        <FxCard />
      </div>

      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Filter by ticker, name or CIK"
          className="h-11 w-full rounded-xl border border-input bg-elevated pr-3 pl-10 outline-none focus-visible:border-primary"
          autoCorrect="off"
          spellCheck={false}
          aria-label="Filter securities"
        />
      </div>

      <div className="no-scrollbar -mx-4 mt-3 flex gap-2 overflow-x-auto px-4 pb-1">
        {[{ exchange: null as string | null, count: exchanges?.reduce((a, e) => a + e.count, 0) ?? 0 }, ...(exchanges ?? [])].map((e) => (
          <button
            key={e.exchange ?? "all"}
            onClick={() => setExchange(e.exchange)}
            className={cn(
              "shrink-0 rounded-full border border-border px-3.5 py-1.5 text-[13px] font-medium transition",
              exchange === e.exchange ? "border-primary bg-primary text-primary-foreground" : "bg-card text-muted-foreground",
            )}
          >
            {e.exchange ?? "All"} <span className="num opacity-70">{fmtInt(e.count)}</span>
          </button>
        ))}
      </div>

      <ErrorNote error={error} />

      <div className="mt-3 overflow-hidden rounded-2xl border border-border/60 bg-card">
        {!data && !error ? (
          <div className="space-y-2 p-3">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="p-4">
            <EmptyState icon={Building2} title={dq ? "No matches" : "No securities loaded"}>
              {dq ? "Try another ticker or company name." : "An administrator can load the SEC EDGAR company list from Administration."}
            </EmptyState>
          </div>
        ) : (
          <ul className="divide-y divide-border/60">
            {items.map((s) => (
              <li key={s.id}>
                <SecurityRow
                  security={s}
                  right={
                    <Button variant="secondary" size="sm" onClick={() => setAdding(s.ticker)} aria-label={`Add ${s.ticker} to watchlist`}>
                      <Plus /> Watch
                    </Button>
                  }
                />
              </li>
            ))}
          </ul>
        )}
      </div>

      {more && (
        <Button variant="outline" className="mt-3 w-full" onClick={() => setSize(size + 1)} disabled={isValidating}>
          {isValidating && <Loader2 className="animate-spin" />} Load more
        </Button>
      )}

      {meta && (
        <SourceLine>
          {fmtInt(meta.total)} results · Source:{" "}
          <a href={meta.source_url} target="_blank" rel="noreferrer" className="underline">
            {meta.source}
          </a>{" "}
          · last synced {meta.last_success_at ? fmtDate(meta.last_success_at, true) : "never"}. Reference data only; no prices.
        </SourceLine>
      )}

      {adding && <AddToWatchlistSheet ticker={adding} open={!!adding} onOpenChange={(o) => !o && setAdding(null)} />}
    </div>
  );
}
