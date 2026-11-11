"use client";

import * as React from "react";
import useSWR from "swr";
import { Check, Plus } from "lucide-react";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorNote } from "@/components/page";
import { api } from "@/lib/api";
import type { Watchlist } from "@/lib/types";

export function AddToWatchlistSheet({
  ticker,
  open,
  onOpenChange,
  onChanged,
}: {
  ticker: string;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onChanged?: () => void;
}) {
  const { data, mutate } = useSWR<Watchlist[]>(open ? "/api/watchlists" : null);
  const [error, setError] = React.useState<unknown>(null);
  const [newName, setNewName] = React.useState("");

  async function toggle(wl: Watchlist) {
    setError(null);
    const item = wl.items.find((i) => i.security.ticker === ticker);
    try {
      if (item) await api(`/api/watchlists/${wl.id}/items/${item.id}`, { method: "DELETE" });
      else await api(`/api/watchlists/${wl.id}/items`, { method: "POST", json: { ticker } });
      await mutate();
      onChanged?.();
    } catch (e) {
      setError(e);
    }
  }

  async function createAndAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    try {
      const wl = await api<Watchlist>("/api/watchlists", { method: "POST", json: { name: newName } });
      await api(`/api/watchlists/${wl.id}/items`, { method: "POST", json: { ticker } });
      setNewName("");
      await mutate();
      onChanged?.();
    } catch (e) {
      setError(e);
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent title={`Add ${ticker} to watchlist`}>
        <div className="space-y-3 px-4 pb-6">
          <ul className="divide-y divide-border/60 overflow-hidden rounded-2xl border border-border/60">
            {data?.map((wl) => {
              const on = wl.items.some((i) => i.security.ticker === ticker);
              return (
                <li key={wl.id}>
                  <button onClick={() => toggle(wl)} className="flex w-full items-center gap-3 px-3.5 py-3.5 text-left active:bg-muted">
                    <span className="flex-1">
                      <span className="block font-medium">{wl.name}</span>
                      <span className="text-[12px] text-muted-foreground">{wl.items.length} securities</span>
                    </span>
                    <span className={`grid size-7 place-items-center rounded-full border ${on ? "border-primary bg-primary text-primary-foreground" : "border-border"}`}>
                      {on && <Check className="size-4" />}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <form onSubmit={createAndAdd} className="flex gap-2">
            <Input placeholder="New watchlist name" value={newName} onChange={(e) => setNewName(e.target.value)} maxLength={80} />
            <Button type="submit" variant="secondary" size="icon" className="size-11 shrink-0" aria-label="Create watchlist">
              <Plus />
            </Button>
          </form>
          <ErrorNote error={error} />
        </div>
      </SheetContent>
    </Sheet>
  );
}
