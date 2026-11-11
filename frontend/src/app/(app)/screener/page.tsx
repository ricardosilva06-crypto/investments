"use client";

import * as React from "react";
import Link from "next/link";
import useSWR from "swr";
import { ArrowDownWideNarrow, ArrowUpNarrowWide, Database, Filter, Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorNote, PageHeader, SourceLine } from "@/components/page";
import { TickerAvatar } from "@/components/security-row";
import { useAuth } from "@/components/providers";
import { api } from "@/lib/api";
import { fmtDate, fmtFinancial, fmtInt } from "@/lib/format";
import type { ScreenerResult } from "@/lib/types";
import { cn } from "@/lib/utils";

type Filters = Record<string, { min?: string; max?: string }>;

// Percent metrics are entered as % in the UI and sent as fractions.
const PRESETS: { name: string; desc: string; filters: Filters; sort: string }[] = [
  { name: "Profitable growers", desc: "Growth ≥ 10%, net margin ≥ 10%", filters: { revenue_growth: { min: "10" }, net_margin: { min: "10" } }, sort: "revenue_growth" },
  { name: "Cash machines", desc: "FCF margin ≥ 15%, revenue ≥ $1B", filters: { fcf_margin: { min: "15" }, revenue: { min: "1000000000" } }, sort: "fcf_margin" },
  { name: "Conservative balance sheet", desc: "Debt/equity ≤ 0.5, current ratio ≥ 1.5", filters: { debt_to_equity: { max: "0.5" }, current_ratio: { min: "1.5" } }, sort: "roe" },
  { name: "High return on equity", desc: "ROE ≥ 20%, positive EPS growth", filters: { roe: { min: "20" }, eps_growth: { min: "0" } }, sort: "roe" },
];

const COLUMNS = ["revenue", "revenue_growth", "net_margin", "roe"];

export default function ScreenerPage() {
  const { user } = useAuth();
  const [filters, setFilters] = React.useState<Filters>({});
  const [sort, setSort] = React.useState("revenue");
  const [order, setOrder] = React.useState<"asc" | "desc">("desc");
  const [exchange, setExchange] = React.useState("");
  const [year, setYear] = React.useState<number | null>(null);
  const [limit, setLimit] = React.useState(50);
  const [open, setOpen] = React.useState(false);
  const [syncing, setSyncing] = React.useState(false);
  const [syncError, setSyncError] = React.useState<unknown>(null);

  const { data: meta } = useSWR<ScreenerResult>("/api/screener?limit=1");
  const kinds = meta?.metrics ?? {};
  const params = new URLSearchParams({ sort, order, limit: String(limit) });
  if (exchange) params.set("exchange", exchange);
  if (year) params.set("year", String(year));
  for (const [k, v] of Object.entries(filters)) {
    const pct = kinds[k]?.kind === "percent";
    if (v.min) params.set(`min_${k}`, String(pct ? Number(v.min) / 100 : v.min));
    if (v.max) params.set(`max_${k}`, String(pct ? Number(v.max) / 100 : v.max));
  }
  const { data, error, isLoading, mutate } = useSWR<ScreenerResult>(meta?.years.length ? `/api/screener?${params}` : null, { keepPreviousData: true });
  const active = Object.entries(filters).filter(([, v]) => v.min || v.max);

  async function sync() {
    setSyncing(true);
    setSyncError(null);
    try {
      await api("/api/admin/screener/sync", { method: "POST" });
      window.location.reload();
    } catch (e) {
      setSyncError(e);
    } finally {
      setSyncing(false);
    }
  }

  if (meta && meta.years.length === 0) {
    return (
      <div>
        <PageHeader title="Screener" subtitle="Screen all US filers using official SEC data" />
        <EmptyState icon={Database} title="Screener data not downloaded yet">
          <p>About 16 requests to SEC EDGAR “frames” download one value per company for each metric, for the latest full year.</p>
          {user?.role === "admin" ? (
            <Button className="mt-3" onClick={sync} disabled={syncing}>
              {syncing && <Loader2 className="animate-spin" />} Download from SEC
            </Button>
          ) : (
            <p className="mt-2">Ask the administrator to download it.</p>
          )}
        </EmptyState>
        <ErrorNote error={syncError ?? (meta.status === "error" ? meta.message : null)} />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Screener"
        subtitle={data?.year ? `${fmtInt(data.total)} of ${fmtInt(data.coverage)} companies · calendar year ${data.year}` : "Loading…"}
        action={
          <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>
            <Filter /> Filters{active.length ? ` (${active.length})` : ""}
          </Button>
        }
      />

      <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 pb-2">
        {PRESETS.map((p) => (
          <button
            key={p.name}
            onClick={() => {
              setFilters(p.filters);
              setSort(p.sort);
              setOrder("desc");
            }}
            className="w-44 shrink-0 rounded-xl border border-border/60 bg-card p-2.5 text-left active:scale-[0.98]"
          >
            <p className="text-[13px] font-semibold">{p.name}</p>
            <p className="text-[11px] text-muted-foreground">{p.desc}</p>
          </button>
        ))}
      </div>

      {active.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {active.map(([k, v]) => (
            <button
              key={k}
              onClick={() => setFilters((f) => ({ ...f, [k]: {} }))}
              className="flex items-center gap-1 rounded-full bg-accent px-2.5 py-1 text-[12px] font-medium text-accent-foreground"
            >
              {kinds[k]?.label} {v.min && `≥ ${v.min}${kinds[k]?.kind === "percent" ? "%" : ""}`} {v.max && `≤ ${v.max}${kinds[k]?.kind === "percent" ? "%" : ""}`}
              <X className="size-3" />
            </button>
          ))}
        </div>
      )}

      <div className="mb-2 flex items-center gap-2">
        <NativeSelect value={sort} onChange={(e) => setSort(e.target.value)} className="h-9 flex-1 text-[14px]" aria-label="Sort by">
          {Object.entries(kinds).map(([k, m]) => (
            <option key={k} value={k}>
              Sort: {m.label}
            </option>
          ))}
        </NativeSelect>
        <Button variant="secondary" size="icon" className="size-9" onClick={() => setOrder(order === "desc" ? "asc" : "desc")} aria-label="Toggle sort order">
          {order === "desc" ? <ArrowDownWideNarrow /> : <ArrowUpNarrowWide />}
        </Button>
      </div>

      <ErrorNote error={error} />
      {(isLoading && !data) || !meta ? <Skeleton className="h-96" /> : null}
      {data && data.items.length === 0 && <EmptyState icon={Filter} title="No company matches all filters">Companies with a missing value never pass a filter on that metric.</EmptyState>}

      {data && data.items.length > 0 && (
        <ul className="divide-y divide-border/60 overflow-hidden rounded-2xl border border-border/60 bg-card">
          {data.items.map((it) => (
            <li key={it.cik}>
              <Link href={it.ticker ? `/company?t=${encodeURIComponent(it.ticker)}` : "#"} className="block px-3.5 py-3 active:bg-muted">
                <div className="flex items-center gap-3">
                  <TickerAvatar ticker={it.ticker ?? "—"} />
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold">
                      {it.ticker} <span className="text-[11px] font-normal text-muted-foreground">{it.exchange}</span>
                    </p>
                    <p className="truncate text-[12px] text-muted-foreground">{it.name}</p>
                  </div>
                  <div className="text-right">
                    <p className="num text-[15px] font-semibold">{fmtFinancial(it.values[sort], kinds[sort]?.kind ?? "money", "USD")}</p>
                    <p className="text-[11px] text-muted-foreground">{kinds[sort]?.label}</p>
                  </div>
                </div>
                <div className="num no-scrollbar mt-2 flex gap-3 overflow-x-auto text-[11.5px]">
                  {COLUMNS.filter((c) => c !== sort).map((c) => (
                    <span key={c} className="shrink-0">
                      <span className="text-muted-foreground">{kinds[c]?.label}</span>{" "}
                      <span className={cn("font-medium", kinds[c]?.kind === "percent" && it.values[c] && Number(it.values[c]) < 0 && "text-negative")}>
                        {fmtFinancial(it.values[c], kinds[c]?.kind ?? "money", "USD")}
                      </span>
                    </span>
                  ))}
                  <span className="shrink-0 text-muted-foreground">FY end {fmtDate(it.period_end)}</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {data && data.total > data.items.length && (
        <Button variant="outline" className="mt-3 w-full" onClick={() => setLimit((l) => Math.min(l + 50, 200))} disabled={limit >= 200}>
          {limit >= 200 ? "Refine filters to see more" : "Show more"}
        </Button>
      )}

      {data && (
        <SourceLine>
          {data.source}. Values are each company’s fiscal year that best matches calendar {data.year} (see FY end).
          Downloaded {fmtDate(data.last_success_at, true)}. Missing values are shown as “—” and never pass a filter.
          P/E only where an end-of-day price is stored. {data.message}
          {user?.role === "admin" && (
            <button onClick={sync} disabled={syncing} className="ml-1 font-medium text-primary underline">
              {syncing ? "Refreshing…" : "Refresh from SEC"}
            </button>
          )}
        </SourceLine>
      )}

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent title="Filters" description="Percentages in %, money in USD, ratios as numbers">
          <div className="space-y-3 px-4 pb-6">
            <div className="grid grid-cols-2 gap-2">
              <Field label="Exchange" htmlFor="ex">
                <NativeSelect id="ex" value={exchange} onChange={(e) => setExchange(e.target.value)}>
                  <option value="">All</option>
                  {["NYSE", "Nasdaq", "CBOE", "OTC"].map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </NativeSelect>
              </Field>
              <Field label="Year" htmlFor="yr">
                <NativeSelect id="yr" value={year ?? ""} onChange={(e) => setYear(e.target.value ? Number(e.target.value) : null)}>
                  {(meta?.years ?? []).map((y) => (
                    <option key={y} value={y}>
                      CY{y}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
            </div>
            {Object.entries(kinds).map(([k, m]) => (
              <div key={k}>
                <p className="mb-1 text-[13px] font-medium text-muted-foreground">
                  {m.label} {m.kind === "percent" ? "(%)" : m.kind === "money" ? "(USD)" : ""}
                </p>
                <div className="grid grid-cols-2 gap-2">
                  <Input inputMode="decimal" placeholder="Min" value={filters[k]?.min ?? ""} onChange={(e) => setFilters((f) => ({ ...f, [k]: { ...f[k], min: e.target.value.replace(",", ".") } }))} />
                  <Input inputMode="decimal" placeholder="Max" value={filters[k]?.max ?? ""} onChange={(e) => setFilters((f) => ({ ...f, [k]: { ...f[k], max: e.target.value.replace(",", ".") } }))} />
                </div>
              </div>
            ))}
            <div className="grid grid-cols-2 gap-2 pt-2">
              <Button variant="secondary" onClick={() => setFilters({})}>
                Clear
              </Button>
              <Button
                onClick={() => {
                  setOpen(false);
                  mutate();
                }}
              >
                Show results
              </Button>
            </div>
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
