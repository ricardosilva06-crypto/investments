"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { Eye, MoreHorizontal, Plus, Search, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/input";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorNote, PageHeader, SourceLine } from "@/components/page";
import { QuoteCell, SecurityRow } from "@/components/security-row";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { WatchItem, Watchlist } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function WatchlistPage() {
  const router = useRouter();
  const params = useSearchParams();
  const { data, error, mutate } = useSWR<Watchlist[]>("/api/watchlists");
  const selectedId = Number(params.get("id")) || data?.[0]?.id;
  const current = data?.find((w) => w.id === selectedId) ?? data?.[0];

  const [manage, setManage] = React.useState<"new" | "edit" | null>(null);
  const [name, setName] = React.useState("");
  const [item, setItem] = React.useState<WatchItem | null>(null);
  const [note, setNote] = React.useState("");
  const [opError, setOpError] = React.useState<unknown>(null);
  const [adding, setAdding] = React.useState(false);
  const [newSec, setNewSec] = React.useState({ ticker: "", name: "" });

  function openAdd() {
    setOpError(null);
    setNewSec({ ticker: "", name: "" });
    setAdding(true);
  }

  function select(id: number) {
    router.replace(`/watchlist?id=${id}`, { scroll: false });
  }

  async function run(fn: () => Promise<unknown>, close?: () => void) {
    setOpError(null);
    try {
      await fn();
      await mutate();
      close?.();
    } catch (e) {
      setOpError(e);
    }
  }

  return (
    <div>
      <PageHeader
        title="Watchlist"
        subtitle={current ? `${current.items.length} securities` : undefined}
        action={
          <Button variant="secondary" size="icon" onClick={openAdd} aria-label="Add security" disabled={!current}>
            <Plus className="size-5" />
          </Button>
        }
      />

      <ErrorNote error={error} />

      {data && (
        <div className="no-scrollbar -mx-4 mb-3 flex gap-2 overflow-x-auto px-4 pb-1">
          {data.map((w) => (
            <button
              key={w.id}
              onClick={() => select(w.id)}
              className={cn(
                "shrink-0 rounded-full border border-border px-3.5 py-1.5 text-[13px] font-medium",
                w.id === current?.id ? "border-primary bg-primary text-primary-foreground" : "bg-card text-muted-foreground",
              )}
            >
              {w.name}
            </button>
          ))}
          <button
            onClick={() => {
              setName("");
              setManage("new");
            }}
            className="flex shrink-0 items-center gap-1 rounded-full border border-dashed border-border px-3 py-1.5 text-[13px] text-muted-foreground"
          >
            <Plus className="size-3.5" /> New
          </button>
        </div>
      )}

      {!data && !error && <Skeleton className="h-48" />}

      {data && data.length === 0 && (
        <EmptyState icon={Eye} title="No watchlists">
          Create one with “New”.
        </EmptyState>
      )}

      {current && (
        <>
          <div className="overflow-hidden rounded-2xl border border-border/60 bg-card">
            {current.items.length === 0 ? (
              <div className="p-4">
                <EmptyState icon={Search} title="This watchlist is empty">
                  <Button variant="secondary" size="sm" className="mt-2" onClick={openAdd}>
                    <Plus /> Add a security
                  </Button>
                </EmptyState>
              </div>
            ) : (
              <ul className="divide-y divide-border/60">
                {current.items.map((i) => (
                  <li key={i.id}>
                    <SecurityRow
                      security={i.security}
                      sub={i.note || i.security.name}
                      quote={<QuoteCell quote={i.quote} />}
                      right={
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`Options for ${i.security.ticker}`}
                          onClick={() => {
                            setItem(i);
                            setNote(i.note);
                          }}
                        >
                          <MoreHorizontal />
                        </Button>
                      }
                    />
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="mt-3 flex justify-between">
            <SourceLine>Last imported end-of-day close and change vs the previous one. Not real-time.</SourceLine>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setName(current.name);
                setManage("edit");
              }}
            >
              Manage list
            </Button>
          </div>
        </>
      )}

      <Sheet open={!!manage} onOpenChange={(o) => !o && setManage(null)}>
        <SheetContent title={manage === "new" ? "New watchlist" : "Manage watchlist"}>
          <form
            className="space-y-3 px-4 pb-6"
            onSubmit={(e) => {
              e.preventDefault();
              run(async () => {
                if (manage === "new") {
                  const w = await api<Watchlist>("/api/watchlists", { method: "POST", json: { name } });
                  select(w.id);
                } else if (current) {
                  await api(`/api/watchlists/${current.id}`, { method: "PATCH", json: { name } });
                }
              }, () => setManage(null));
            }}
          >
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name" maxLength={80} required autoFocus />
            <ErrorNote error={opError} />
            <Button type="submit" className="w-full">
              {manage === "new" ? "Create" : "Rename"}
            </Button>
            {manage === "edit" && current && (
              <Button
                type="button"
                variant="destructive"
                className="w-full"
                onClick={() => {
                  if (!confirm(`Delete “${current.name}” and its ${current.items.length} entries?`)) return;
                  run(() => api(`/api/watchlists/${current.id}`, { method: "DELETE" }), () => {
                    setManage(null);
                    router.replace("/watchlist");
                  });
                }}
              >
                <Trash2 /> Delete watchlist
              </Button>
            )}
          </form>
        </SheetContent>
      </Sheet>

      <Sheet open={adding} onOpenChange={setAdding}>
        <SheetContent title="Add to watchlist" description={current?.name}>
          <form
            className="space-y-3 px-4 pb-6"
            onSubmit={(e) => {
              e.preventDefault();
              if (!current) return;
              run(() => api(`/api/watchlists/${current.id}/items`, { method: "POST", json: newSec }), () => setAdding(false));
            }}
          >
            <Field label="Ticker" htmlFor="wt">
              <Input
                id="wt"
                value={newSec.ticker}
                onChange={(e) => setNewSec({ ...newSec, ticker: e.target.value.toUpperCase() })}
                placeholder="e.g. ASML.AS, NOVO-B.CO, AAPL"
                autoCapitalize="characters"
                autoCorrect="off"
                required
                maxLength={20}
                autoFocus
              />
            </Field>
            <Field label="Name (optional)" htmlFor="wn">
              <Input id="wn" value={newSec.name} onChange={(e) => setNewSec({ ...newSec, name: e.target.value })} placeholder="e.g. ASML Holding" maxLength={120} />
            </Field>
            <p className="text-[12px] text-muted-foreground">Use the same ticker as in your broker export so prices and holdings match.</p>
            <ErrorNote error={opError} />
            <Button type="submit" className="w-full">
              Add
            </Button>
          </form>
        </SheetContent>
      </Sheet>

      <Sheet open={!!item} onOpenChange={(o) => !o && setItem(null)}>
        {item && current && (
          <SheetContent title={item.security.ticker} description={`${item.security.name} · added ${fmtDate(item.added_at)}`}>
            <form
              className="space-y-3 px-4 pb-6"
              onSubmit={(e) => {
                e.preventDefault();
                run(() => api(`/api/watchlists/${current.id}/items/${item.id}`, { method: "PATCH", json: { note } }), () => setItem(null));
              }}
            >
              <Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why are you watching this? (private)" maxLength={2000} className="min-h-24" />
              <ErrorNote error={opError} />
              <div className="grid grid-cols-2 gap-2">
                <Button type="button" variant="secondary" asChild>
                  <Link href={`/prices?t=${encodeURIComponent(item.security.ticker)}`}>Prices</Link>
                </Button>
                <Button type="submit">Save note</Button>
              </div>
              <Button
                type="button"
                variant="destructive"
                className="w-full"
                onClick={() => run(() => api(`/api/watchlists/${current.id}/items/${item.id}`, { method: "DELETE" }), () => setItem(null))}
              >
                <Trash2 /> Remove from {current.name}
              </Button>
            </form>
          </SheetContent>
        )}
      </Sheet>
    </div>
  );
}
