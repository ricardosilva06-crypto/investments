"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { Building2, Eye, FileText, Loader2, Search, Wallet } from "lucide-react";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import type { SearchHit } from "@/lib/types";

const ICONS = { security: Building2, note: FileText, watchlist: Eye, holding: Wallet } as const;
const GROUPS: { type: SearchHit["type"]; label: string }[] = [
  { type: "holding", label: "Your holdings" },
  { type: "watchlist", label: "Watchlists" },
  { type: "note", label: "Notes" },
  { type: "security", label: "Companies (SEC EDGAR)" },
];

function useDebounced<T>(value: T, ms: number) {
  const [v, setV] = React.useState(value);
  React.useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function SearchSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const router = useRouter();
  const [q, setQ] = React.useState("");
  const dq = useDebounced(q.trim(), 200);
  const { data, isLoading, error } = useSWR<SearchHit[]>(dq ? `/api/search?q=${encodeURIComponent(dq)}` : null);

  function setOpen(o: boolean) {
    if (!o) setQ("");
    onOpenChange(o);
  }

  function go(href: string) {
    setOpen(false);
    router.push(href);
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetContent title="Search" full hideTitle>
        <div className="sticky top-0 z-10 flex items-center gap-2 bg-card px-4 pt-3 pb-3">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && data?.[0]) go(data[0].href);
              }}
              placeholder="Ticker, company, note…"
              enterKeyHint="search"
              autoCapitalize="characters"
              autoCorrect="off"
              spellCheck={false}
              className="h-11 w-full rounded-xl border border-input bg-elevated pr-10 pl-10 outline-none focus-visible:border-primary"
              aria-label="Search"
            />
            {isLoading && <Loader2 className="absolute top-1/2 right-3.5 size-4 -translate-y-1/2 animate-spin text-muted-foreground" />}
          </div>
          <button onClick={() => setOpen(false)} className="px-1 text-[15px] font-medium text-primary">
            Cancel
          </button>
        </div>
        <div className="px-4 pb-8">
          {!dq && (
            <p className="mt-6 text-center text-sm text-muted-foreground">
              Search US-listed companies from the SEC EDGAR list, plus your own holdings, watchlists and notes.
            </p>
          )}
          {error && <p className="mt-6 text-center text-sm text-negative">{(error as Error).message}</p>}
          {dq && data && data.length === 0 && (
            <p className="mt-6 text-center text-sm text-muted-foreground">
              No results for “{dq}”. If the company list is empty, an administrator needs to sync it from SEC EDGAR.
            </p>
          )}
          {data &&
            GROUPS.map(({ type, label }) => {
              const hits = data.filter((h) => h.type === type);
              if (!hits.length) return null;
              return (
                <section key={type} className="mt-3">
                  <h3 className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</h3>
                  <ul className="divide-y divide-border/60 overflow-hidden rounded-2xl border border-border/60 bg-elevated/40">
                    {hits.map((h, i) => {
                      const Icon = ICONS[h.type];
                      return (
                        <li key={`${h.href}-${i}`}>
                          <button onClick={() => go(h.href)} className="flex w-full items-center gap-3 px-3.5 py-3 text-left active:bg-muted">
                            <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-accent text-accent-foreground">
                              <Icon className="size-4" />
                            </span>
                            <span className="min-w-0">
                              <span className="block truncate font-semibold">{h.title}</span>
                              <span className="block truncate text-[13px] text-muted-foreground">{h.subtitle}</span>
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              );
            })}
        </div>
      </SheetContent>
    </Sheet>
  );
}
