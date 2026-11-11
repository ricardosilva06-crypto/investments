"use client";

import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { AlertTriangle, ChevronDown, ExternalLink, Eye, Loader2, NotebookPen, RefreshCw, Scale, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Segmented } from "@/components/ui/segmented";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorNote, SourceLine } from "@/components/page";
import { TickerAvatar } from "@/components/security-row";
import { AddToWatchlistSheet } from "@/components/add-to-watchlist";
import { PricePanel } from "@/components/company/price-panel";
import { Statements } from "@/components/company/statements";
import { Filings } from "@/components/company/filings";
import { ProvenanceSheet, type Provenance } from "@/components/company/provenance-sheet";
import { api } from "@/lib/api";
import { fmtDate, fmtFinancial, fmtPct, fmtPrice, fmtRelative, signClass } from "@/lib/format";
import type { Company, Note } from "@/lib/types";
import { cn } from "@/lib/utils";

type Tab = "overview" | "financials" | "filings" | "notes";
type Detail = { watchlist_ids: number[]; edgar_url: string | null };

function Expandable({ title, defaultOpen = false, children }: { title: string; defaultOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = React.useState(defaultOpen);
  return (
    <section className="overflow-hidden rounded-2xl border border-border/60 bg-card">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-center gap-3 px-4 py-3.5 text-left">
        <span className="flex-1 font-semibold">{title}</span>
        <ChevronDown className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      {open && <div className="border-t border-border/60 px-4 py-3">{children}</div>}
    </section>
  );
}

function fye(mmdd: string) {
  if (mmdd.length !== 4) return "—";
  const d = new Date(2000, Number(mmdd.slice(0, 2)) - 1, Number(mmdd.slice(2)));
  return new Intl.DateTimeFormat(undefined, { day: "numeric", month: "long" }).format(d);
}

function Overview({ c, onProv }: { c: Company; onProv: (p: Provenance) => void }) {
  const p = c.profile;
  return (
    <div className="space-y-3">
      <PricePanel ticker={c.security.ticker} />

      {c.key_figures.length > 0 ? (
        <div>
          <p className="mb-1.5 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
            Latest fiscal year · ended {fmtDate(c.key_figures[0].period_end)}
          </p>
          <div className="grid grid-cols-2 gap-2">
            {c.key_figures.map((k) => (
              <button
                key={k.key}
                onClick={() =>
                  onProv({
                    label: k.label,
                    period: `Fiscal year ended ${fmtDate(k.period_end)}`,
                    kind: k.kind,
                    currency: c.currency,
                    cell: { value: k.value, concept: k.concept, unit: "", accession: "", form: k.form, filed: k.filed, derived: k.derived, formula: k.formula },
                  })
                }
                className="rounded-xl bg-card px-3 py-2.5 text-left ring-1 ring-border/60 active:scale-[0.98]"
              >
                <p className="truncate text-[11px] uppercase tracking-wide text-muted-foreground">
                  {k.label}
                  {k.derived && <sup className="ml-0.5 text-warning">c</sup>}
                </p>
                <p className={cn("num mt-0.5 text-[17px] font-semibold", k.kind === "percent" && k.key.includes("growth") && signClass(k.value))}>
                  {k.kind === "percent" && k.key.includes("growth") ? fmtPct(k.value, 1) : fmtFinancial(k.value, k.kind, c.currency)}
                </p>
              </button>
            ))}
          </div>
          <SourceLine>
            From SEC XBRL filings. <sup className="text-warning">c</sup> = calculated. Tap a figure to see its filing or formula.
          </SourceLine>
        </div>
      ) : (
        <p className="rounded-2xl border border-dashed border-border p-4 text-[13px] text-muted-foreground">
          {c.security.cik
            ? "No XBRL financial data is available for this company yet (or it has not been downloaded)."
            : "This security has no SEC CIK, so SEC financial data is not available."}
        </p>
      )}

      {p && (
        <Expandable title="Company profile" defaultOpen>
          <dl className="space-y-2 text-[14px]">
            {[
              ["Industry (SIC)", p.sic_description ? `${p.sic_description} (${p.sic})` : "—"],
              ["Filer category", p.category || "—"],
              ["Fiscal year end", fye(p.fiscal_year_end)],
              ["Incorporated in", p.state_of_incorporation || "—"],
              ["Business address", p.business_address || "—"],
              ["Phone", p.phone || "—"],
              ["Tickers", p.tickers.join(", ") || "—"],
              ["SEC CIK", String(p.cik)],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between gap-4">
                <dt className="shrink-0 text-muted-foreground">{k}</dt>
                <dd className="text-right">{v}</dd>
              </div>
            ))}
            {(p.website || p.investor_website) && (
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">Website</dt>
                <dd className="truncate text-right">
                  <a className="text-primary" href={p.investor_website || p.website} target="_blank" rel="noreferrer">
                    {(p.investor_website || p.website).replace(/^https?:\/\//, "")}
                  </a>
                </dd>
              </div>
            )}
            {p.former_names.length > 0 && (
              <div>
                <dt className="text-muted-foreground">Former names</dt>
                <dd className="mt-0.5 text-[13px]">{p.former_names.map((f) => f.name).join(" · ")}</dd>
              </div>
            )}
          </dl>
        </Expandable>
      )}
    </div>
  );
}

function NotesTab({ ticker }: { ticker: string }) {
  const { data: notes } = useSWR<Note[]>(`/api/notes?ticker=${encodeURIComponent(ticker)}`);
  return (
    <div className="space-y-2">
      <Button variant="secondary" className="w-full" asChild>
        <Link href={`/notes?new=1&t=${encodeURIComponent(ticker)}`}>
          <NotebookPen /> New note on {ticker}
        </Link>
      </Button>
      {notes?.length === 0 && <p className="py-4 text-center text-[13px] text-muted-foreground">No private notes on {ticker} yet.</p>}
      {notes?.map((n) => (
        <Link key={n.id} href={`/notes?id=${n.id}`} className="block rounded-2xl border border-border/60 bg-card p-3.5 active:scale-[0.99]">
          <span className="block font-semibold">{n.title}</span>
          <span className="line-clamp-3 text-[13px] text-muted-foreground">{n.body || "No content"}</span>
          <span className="text-[11px] text-muted-foreground">Edited {fmtRelative(n.updated_at)}</span>
        </Link>
      ))}
    </div>
  );
}

export default function CompanyPage() {
  const t = (useSearchParams().get("t") ?? "").toUpperCase();
  const key = t ? `/api/companies/${encodeURIComponent(t)}` : null;
  const { data, error, mutate } = useSWR<Company>(key, { revalidateOnFocus: false });
  const { data: detail, mutate: mutateDetail } = useSWR<Detail>(t ? `/api/securities/${encodeURIComponent(t)}` : null);
  const [tab, setTab] = React.useState<Tab>("overview");
  const [watchOpen, setWatchOpen] = React.useState(false);
  const [prov, setProv] = React.useState<Provenance | null>(null);
  const [refreshing, setRefreshing] = React.useState(false);
  const [refreshError, setRefreshError] = React.useState<unknown>(null);

  if (!t) return <ErrorNote error="No ticker given." />;
  if (error) return <ErrorNote error={error} />;
  if (!data)
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <Skeleton className="size-10" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-6 w-24" />
            <Skeleton className="h-4 w-40" />
          </div>
        </div>
        <p className="text-[13px] text-muted-foreground">Loading {t}. The first visit downloads its filings from SEC EDGAR…</p>
        <Skeleton className="h-56" />
        <Skeleton className="h-28" />
      </div>
    );

  const s = data.security;
  const q = data.quote;
  const watching = (detail?.watchlist_ids.length ?? 0) > 0;
  const errors = Object.entries(data.errors);
  const facts = data.freshness.find((f) => f.source === "sec_companyfacts");

  async function refresh() {
    setRefreshing(true);
    setRefreshError(null);
    try {
      await mutate(await api<Company>(`/api/companies/${encodeURIComponent(t)}/refresh`, { method: "POST" }), { revalidate: false });
    } catch (e) {
      setRefreshError(e);
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <div>
      <div className="flex items-start gap-3">
        <TickerAvatar ticker={s.ticker} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <h1 className="text-2xl font-bold tracking-tight">{s.ticker}</h1>
            {s.exchange && <Badge variant="muted">{s.exchange}</Badge>}
            {!s.is_listed && <Badge variant="warning">Not in latest SEC list</Badge>}
          </div>
          <p className="truncate text-[14px] text-muted-foreground">{data.profile?.name ?? s.name}</p>
        </div>
      </div>

      {q && (
        <div className="mt-3 flex items-end justify-between gap-3">
          <div>
            <p className="num text-[30px] font-bold leading-none tracking-tight">{fmtPrice(q.close, q.currency)}</p>
            <p className="mt-1 text-[12px] text-muted-foreground">
              Close {fmtDate(q.date)} · end of day, not live
            </p>
          </div>
          {q.change_pct !== null && (
            <span className={cn("num rounded-lg px-2 py-1 text-[14px] font-semibold", Number(q.change_pct) >= 0 ? "bg-positive/15 text-positive" : "bg-negative/15 text-negative")}>
              {fmtPct(q.change_pct)}
            </span>
          )}
        </div>
      )}

      <div className="mt-4 grid grid-cols-2 gap-2">
        <Button variant={watching ? "secondary" : "default"} onClick={() => setWatchOpen(true)}>
          <Eye /> {watching ? `Watching (${detail!.watchlist_ids.length})` : "Watch"}
        </Button>
        <Button variant="secondary" asChild>
          <Link href={`/notes?new=1&t=${encodeURIComponent(s.ticker)}`}>
            <NotebookPen /> Add note
          </Link>
        </Button>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-2">
        <Button variant="outline" size="sm" asChild>
          <Link href={`/analyst?task=company_analysis&t=${encodeURIComponent(s.ticker)}`}>
            <Sparkles /> AI analysis
          </Link>
        </Button>
        <Button variant="outline" size="sm" asChild>
          <Link href={`/analyst?task=bull_bear&t=${encodeURIComponent(s.ticker)}`}>
            <Scale /> Bull vs bear
          </Link>
        </Button>
      </div>

      {errors.length > 0 && (
        <div className="mt-3 flex gap-2 rounded-xl bg-warning/10 px-3 py-2 text-[12px] text-warning">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <span>
            {errors.map(([k, v]) => `${k.replace("sec_", "SEC ").replace("_", " ")}: ${v}`).join(" · ")} Showing the last stored data, if any.
          </span>
        </div>
      )}

      <div className="sticky top-[calc(56px+env(safe-area-inset-top))] z-20 -mx-4 mt-2 bg-background/95 px-4 py-2 backdrop-blur-xl">
        <Segmented
          value={tab}
          onChange={setTab}
          options={[
            { value: "overview", label: "Overview" },
            { value: "financials", label: "Financials" },
            { value: "filings", label: "Filings" },
            { value: "notes", label: "Notes" },
          ]}
        />
      </div>

      <div className="mt-3">
        {tab === "overview" && <Overview c={data} onProv={setProv} />}
        {tab === "financials" &&
          (data.has_financials ? (
            <Statements ticker={s.ticker} />
          ) : (
            <p className="rounded-2xl border border-dashed border-border p-4 text-center text-[13px] text-muted-foreground">
              No XBRL financial statements are available for {s.ticker}.
            </p>
          ))}
        {tab === "filings" && <Filings ticker={s.ticker} />}
        {tab === "notes" && <NotesTab ticker={s.ticker} />}
      </div>

      <div className="mt-5 flex items-center justify-between gap-2 border-t border-border/60 pt-3">
        <p className="text-[11.5px] text-muted-foreground">
          SEC data {facts?.last_success_at ? `downloaded ${fmtRelative(facts.last_success_at)}` : "not downloaded"}
          {detail?.edgar_url && (
            <>
              {" · "}
              <a href={detail.edgar_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 underline">
                EDGAR <ExternalLink className="size-3" />
              </a>
            </>
          )}
        </p>
        <Button variant="ghost" size="sm" onClick={refresh} disabled={refreshing || !s.cik}>
          {refreshing ? <Loader2 className="animate-spin" /> : <RefreshCw />} Refresh
        </Button>
      </div>
      <ErrorNote error={refreshError} />

      <AddToWatchlistSheet ticker={s.ticker} open={watchOpen} onOpenChange={setWatchOpen} onChanged={() => mutateDetail()} />
      <ProvenanceSheet p={prov} onClose={() => setProv(null)} />
    </div>
  );
}
