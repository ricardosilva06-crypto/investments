"use client";

import * as React from "react";
import useSWR from "swr";
import { ExternalLink, FileText, Loader2, Newspaper, Plus, RefreshCw, Rss, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Segmented } from "@/components/ui/segmented";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorNote, PageHeader, SourceLine } from "@/components/page";
import { useAuth } from "@/components/providers";
import { api } from "@/lib/api";
import { fmtRelative } from "@/lib/format";
import type { FeedItem, NewsEntry } from "@/lib/types";

type NewsResp = { items: NewsEntry[]; tracked_tickers: string[]; note: string };

function FeedManager({ open, onOpenChange, onChanged }: { open: boolean; onOpenChange: (o: boolean) => void; onChanged: () => void }) {
  const { data: feeds, mutate } = useSWR<FeedItem[]>(open ? "/api/feeds" : null);
  const { data: suggested } = useSWR<{ title: string; url: string }[]>(open ? "/api/feeds/suggested" : null);
  const [url, setUrl] = React.useState("");
  const [title, setTitle] = React.useState("");
  const [ticker, setTicker] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);

  async function add(u = url, t = title, tk = ticker) {
    setBusy(true);
    setError(null);
    try {
      await api("/api/admin/feeds", { method: "POST", json: { url: u, title: t, ticker: tk || null } });
      setUrl("");
      setTitle("");
      setTicker("");
      mutate();
      onChanged();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const have = new Set(feeds?.map((f) => f.url));
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent title="News feeds" description="RSS/Atom feeds, shared by all members">
        <div className="space-y-3 px-4 pb-6">
          <form
            className="space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              add();
            }}
          >
            <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://… feed URL" inputMode="url" required />
            <div className="grid grid-cols-[1fr_7rem] gap-2">
              <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Name (optional)" maxLength={160} />
              <Input value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} placeholder="Ticker" maxLength={20} autoCapitalize="characters" />
            </div>
            <ErrorNote error={error} />
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? <Loader2 className="animate-spin" /> : <Plus />} Add feed
            </Button>
            <p className="text-[12px] text-muted-foreground">
              Link a ticker for company feeds (e.g. an investor-relations RSS) so they appear under “My companies”. Only add feeds whose terms allow personal use.
            </p>
          </form>
          {suggested && suggested.some((s) => !have.has(s.url)) && (
            <div>
              <p className="mb-1.5 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">Suggested official feeds</p>
              <div className="flex flex-wrap gap-1.5">
                {suggested
                  .filter((s) => !have.has(s.url))
                  .map((s) => (
                    <button key={s.url} onClick={() => add(s.url, s.title, "")} className="rounded-full bg-elevated px-3 py-1.5 text-[12px] font-medium">
                      + {s.title}
                    </button>
                  ))}
              </div>
            </div>
          )}
          <ul className="divide-y divide-border/60 overflow-hidden rounded-2xl border border-border/60">
            {feeds?.map((f) => (
              <li key={f.id} className="flex items-center gap-2 px-3 py-2.5">
                <Rss className="size-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[14px] font-medium">
                    {f.title} {f.ticker && <Badge>{f.ticker}</Badge>}
                  </p>
                  <p className="truncate text-[11px] text-muted-foreground">
                    {f.status === "error" ? <span className="text-negative">{f.message}</span> : `Updated ${fmtRelative(f.last_fetch_at)}`}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Remove feed"
                  onClick={async () => {
                    await api(`/api/admin/feeds/${f.id}`, { method: "DELETE" });
                    mutate();
                    onChanged();
                  }}
                >
                  <Trash2 className="text-muted-foreground" />
                </Button>
              </li>
            ))}
            {feeds?.length === 0 && <li className="p-3 text-[13px] text-muted-foreground">No feeds yet.</li>}
          </ul>
        </div>
      </SheetContent>
    </Sheet>
  );
}

export default function NewsPage() {
  const { user } = useAuth();
  const [scope, setScope] = React.useState<"mine" | "all">("mine");
  const [manage, setManage] = React.useState(false);
  const [refreshing, setRefreshing] = React.useState(false);
  const { data, error, mutate, isLoading } = useSWR<NewsResp>(`/api/news?scope=${scope}&limit=80`);

  return (
    <div>
      <PageHeader
        title="News"
        subtitle="Headlines from feeds you trust, and SEC filings of your companies"
        action={
          user?.role === "admin" ? (
            <Button variant="secondary" size="sm" onClick={() => setManage(true)}>
              <Rss /> Feeds
            </Button>
          ) : undefined
        }
      />
      <Segmented
        value={scope}
        onChange={setScope}
        options={[
          { value: "mine", label: "My companies" },
          { value: "all", label: "All feeds" },
        ]}
      />
      <ErrorNote error={error} />
      {isLoading && !data && <Skeleton className="mt-3 h-64" />}
      {data && data.items.length === 0 && (
        <div className="mt-3">
          <EmptyState icon={Newspaper} title="No news yet">
            {scope === "mine"
              ? data.tracked_tickers.length
                ? "No filings or company feeds for your watchlist and holdings yet."
                : "Add companies to a watchlist or portfolio to see their SEC filings here."
              : user?.role === "admin"
                ? "Add RSS feeds with the Feeds button."
                : "The administrator has not added any feeds yet."}
          </EmptyState>
        </div>
      )}
      <ul className="mt-3 space-y-2">
        {data?.items.map((n, i) => (
          <li key={`${n.link}-${i}`}>
            <a href={n.link || undefined} target="_blank" rel="noreferrer noopener" className="block rounded-2xl border border-border/60 bg-card p-3.5 active:scale-[0.99]">
              <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                {n.type === "filing" ? <FileText className="size-3.5" /> : <Newspaper className="size-3.5" />}
                <span className="truncate">{n.source}</span>
                {n.ticker && <Badge variant="muted">{n.ticker}</Badge>}
                <span className="ml-auto shrink-0">{n.date_is_published ? fmtRelative(n.date) : `seen ${fmtRelative(n.date)}`}</span>
              </div>
              <p className="mt-1 text-[15px] leading-snug font-semibold">{n.title}</p>
              {n.summary && <p className="mt-1 line-clamp-2 text-[13px] text-muted-foreground">{n.summary}</p>}
              {n.link && (
                <span className="mt-1.5 inline-flex items-center gap-1 text-[12px] font-medium text-primary">
                  Read at source <ExternalLink className="size-3" />
                </span>
              )}
            </a>
          </li>
        ))}
      </ul>
      {data && (
        <SourceLine>
          {data.note} Feeds refresh every 30 minutes.
          {user?.role === "admin" && (
            <button
              className="ml-1 inline-flex items-center gap-1 font-medium text-primary underline"
              disabled={refreshing}
              onClick={async () => {
                setRefreshing(true);
                await api("/api/admin/feeds/refresh", { method: "POST" }).catch(() => {});
                await mutate();
                setRefreshing(false);
              }}
            >
              <RefreshCw className="size-3" /> {refreshing ? "Refreshing…" : "Refresh now"}
            </button>
          )}
        </SourceLine>
      )}
      {user?.role === "admin" && <FeedManager open={manage} onOpenChange={setManage} onChanged={() => mutate()} />}
    </div>
  );
}
