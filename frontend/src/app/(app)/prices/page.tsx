"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { ChevronLeft, Download, LineChart, Loader2, Plus, Trash2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorNote, PageHeader, SourceLine } from "@/components/page";
import { QuoteCell, SecurityRow } from "@/components/security-row";
import { api } from "@/lib/api";
import { fmtDate, fmtInt, fmtPrice } from "@/lib/format";
import { ECB_SOURCE, fetchEcbRates } from "@/lib/local/ecb";
import type { FxRate, Prices, SecurityListItem } from "@/lib/types";

const LineMini = dynamic(() => import("@/components/charts/line-mini"), { ssr: false, loading: () => <Skeleton className="h-40" /> });

const CURRENCIES = ["EUR", "USD", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN", "JPY", "CAD", "AUD", "BRL"];

function ImportPricesSheet({ ticker, open, onOpenChange, onDone }: { ticker?: string; open: boolean; onOpenChange: (o: boolean) => void; onDone: (t: string) => void }) {
  const [f, setF] = React.useState({ ticker: ticker ?? "", currency: "EUR", source: "" });
  const [file, setFile] = React.useState<File | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);
  const [result, setResult] = React.useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    if (file.size > 5_000_000) return setError(new Error("File is larger than 5 MB."));
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const t = f.ticker.trim().toUpperCase();
      const r = await api<{ ticker: string; imported: number; last: string }>(`/api/prices/${encodeURIComponent(t)}/import`, {
        method: "POST",
        json: { csv: await file.text(), source: f.source, currency: f.currency },
      });
      setResult(`Imported ${r.imported} daily closes for ${r.ticker} (latest ${fmtDate(r.last)}).`);
      onDone(r.ticker);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent title="Import prices" description="Daily closes from a CSV file (e.g. your broker's export)">
        <form onSubmit={submit} className="space-y-3 px-4 pb-6">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Ticker" htmlFor="pt">
              <Input id="pt" value={f.ticker} onChange={(e) => setF({ ...f, ticker: e.target.value.toUpperCase() })} placeholder="ASML.AS" required maxLength={20} autoCapitalize="characters" autoCorrect="off" readOnly={!!ticker} />
            </Field>
            <Field label="Currency" htmlFor="pc">
              <NativeSelect id="pc" value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value })}>
                {CURRENCIES.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </NativeSelect>
            </Field>
          </div>
          <Field label="Where is this data from?" htmlFor="ps">
            <Input id="ps" value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })} placeholder="e.g. My broker export" required minLength={2} maxLength={48} />
          </Field>
          <Field label="CSV file (header with Date and Close; Open/High/Low/Volume optional)" htmlFor="pf">
            <Input id="pf" type="file" accept=".csv,text/csv,text/plain" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required className="py-2" />
          </Field>
          <ErrorNote error={error} />
          {result && <p className="text-[13px] text-positive">{result}</p>}
          <Button type="submit" className="w-full" disabled={busy || !file}>
            {busy ? <Loader2 className="animate-spin" /> : <Upload />} Import prices
          </Button>
          <p className="text-[11.5px] text-muted-foreground">Existing closes for the same dates are replaced. Use the same ticker as in your transactions.</p>
        </form>
      </SheetContent>
    </Sheet>
  );
}

function FxSection() {
  const { data, error, mutate } = useSWR<FxRate[]>("/api/fx");
  const [f, setF] = React.useState({ currency: "USD", value: "", date: "" });
  const [opError, setOpError] = React.useState<unknown>(null);
  const [msg, setMsg] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setOpError(null);
    setMsg(null);
    try {
      await api("/api/fx", { method: "PUT", json: { ...f, date: f.date || undefined } });
      setF({ ...f, value: "" });
      mutate();
    } catch (err) {
      setOpError(err);
    }
  }

  async function downloadEcb() {
    setBusy(true);
    setOpError(null);
    setMsg(null);
    try {
      const rates = await fetchEcbRates();
      for (const r of rates) await api("/api/fx", { method: "PUT", json: { ...r, source: ECB_SOURCE } });
      setMsg(`Saved ${rates.length} ECB reference rates of ${fmtDate(rates[0].date)}.`);
      mutate();
    } catch (err) {
      setOpError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>Exchange rates</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-[13px] text-muted-foreground">Used only to show a portfolio total in your base currency. Rates are “1 EUR = x”.</p>
        <ErrorNote error={error} />
        {data && data.length > 0 && (
          <ul className="divide-y divide-border/60 overflow-hidden rounded-xl border border-border/60">
            {data.map((r) => (
              <li key={r.currency} className="flex items-center gap-3 px-3 py-2.5">
                <span className="w-20 font-semibold">EUR/{r.currency}</span>
                <span className="flex-1">
                  <span className="num block">{r.value}</span>
                  <span className="block text-[11px] text-muted-foreground">
                    {fmtDate(r.date)} · {r.source}
                  </span>
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Delete EUR/${r.currency}`}
                  onClick={async () => {
                    await api(`/api/fx/${r.currency}`, { method: "DELETE" });
                    mutate();
                  }}
                >
                  <Trash2 className="text-muted-foreground" />
                </Button>
              </li>
            ))}
          </ul>
        )}
        <form onSubmit={save} className="grid grid-cols-[1fr_1.3fr_auto] items-end gap-2">
          <Field label="Currency" htmlFor="fc">
            <NativeSelect id="fc" value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value })}>
              {CURRENCIES.filter((c) => c !== "EUR").map((c) => (
                <option key={c}>{c}</option>
              ))}
            </NativeSelect>
          </Field>
          <Field label="1 EUR =" htmlFor="fv">
            <Input id="fv" inputMode="decimal" value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} placeholder="1.08" required />
          </Field>
          <Button type="submit" size="icon" className="size-11" aria-label="Save rate">
            <Plus />
          </Button>
        </form>
        <Button variant="secondary" className="w-full" onClick={downloadEcb} disabled={busy}>
          {busy ? <Loader2 className="animate-spin" /> : <Download />} Download latest ECB rates
        </Button>
        <ErrorNote error={opError} />
        {msg && <p className="text-[13px] text-positive">{msg}</p>}
        <SourceLine>ECB euro reference rates: free, reuse permitted with attribution. They are not trading rates.</SourceLine>
      </CardContent>
    </Card>
  );
}

function TickerView({ ticker }: { ticker: string }) {
  const router = useRouter();
  const { data, error, mutate } = useSWR<Prices>(`/api/prices/${encodeURIComponent(ticker)}`);
  const { data: list, mutate: mutateList } = useSWR<SecurityListItem[]>("/api/securities");
  const sec = list?.find((x) => x.ticker === ticker);
  const [importOpen, setImportOpen] = React.useState(false);
  const [edit, setEdit] = React.useState<{ name: string; exchange: string } | null>(null);
  const [opError, setOpError] = React.useState<unknown>(null);
  const last = data?.bars.at(-1);
  const points = (data?.bars ?? []).slice(-260).map((b) => ({ date: b.date, value: Number(b.close) }));

  return (
    <div>
      <Link href="/prices" className="mb-2 inline-flex items-center gap-1 text-[14px] font-medium text-primary">
        <ChevronLeft className="size-4" /> Prices
      </Link>
      <PageHeader
        title={ticker}
        subtitle={sec && sec.name !== ticker ? `${sec.name}${sec.exchange ? ` · ${sec.exchange}` : ""}` : sec?.exchange ?? undefined}
        action={
          <Button variant="secondary" size="sm" onClick={() => setEdit({ name: sec?.name === ticker ? "" : (sec?.name ?? ""), exchange: sec?.exchange ?? "" })}>
            Edit
          </Button>
        }
      />
      <ErrorNote error={error} />
      {!data && !error && <Skeleton className="h-48" />}
      {data && (
        <Card>
          <CardContent className="pt-4">
            {last ? (
              <>
                <p className="num text-3xl font-bold">{fmtPrice(last.close, last.currency)}</p>
                <p className="text-[12px] text-muted-foreground">
                  Close of {fmtDate(last.date)} · {fmtInt(data.bars.length)} days stored
                </p>
                <div className="mt-3">
                  <LineMini points={points} digits={2} />
                </div>
                <SourceLine>
                  {data.note} Source: {data.sources.join(", ")}. Chart shows the last {points.length} stored closes.
                </SourceLine>
              </>
            ) : (
              <EmptyState icon={LineChart} title="No prices yet">
                Import daily closes from a CSV to value holdings and see a chart.
              </EmptyState>
            )}
          </CardContent>
        </Card>
      )}
      <div className="mt-4 grid grid-cols-2 gap-2">
        <Button onClick={() => setImportOpen(true)}>
          <Upload /> Import CSV
        </Button>
        <Button
          variant="destructive"
          disabled={!last}
          onClick={async () => {
            if (!confirm(`Delete all stored prices for ${ticker}?`)) return;
            await api(`/api/prices/${encodeURIComponent(ticker)}`, { method: "DELETE" });
            mutate();
            mutateList();
          }}
        >
          <Trash2 /> Delete prices
        </Button>
      </div>
      <ImportPricesSheet ticker={ticker} open={importOpen} onOpenChange={setImportOpen} onDone={() => { mutate(); mutateList(); }} />
      <Sheet open={!!edit} onOpenChange={(o) => !o && setEdit(null)}>
        {edit && (
          <SheetContent title={`Edit ${ticker}`}>
            <form
              className="space-y-3 px-4 pb-6"
              onSubmit={async (e) => {
                e.preventDefault();
                setOpError(null);
                try {
                  await api(`/api/securities/${encodeURIComponent(ticker)}`, { method: "PUT", json: edit });
                  await mutateList();
                  setEdit(null);
                  router.refresh();
                } catch (err) {
                  setOpError(err);
                }
              }}
            >
              <Field label="Name" htmlFor="sn">
                <Input id="sn" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} maxLength={120} placeholder="Company name" />
              </Field>
              <Field label="Exchange (optional)" htmlFor="sx">
                <Input id="sx" value={edit.exchange} onChange={(e) => setEdit({ ...edit, exchange: e.target.value })} maxLength={32} placeholder="e.g. Euronext Amsterdam" />
              </Field>
              <ErrorNote error={opError} />
              <Button type="submit" className="w-full">
                Save
              </Button>
            </form>
          </SheetContent>
        )}
      </Sheet>
    </div>
  );
}

export default function PricesPage() {
  const router = useRouter();
  const params = useSearchParams();
  const ticker = params.get("t")?.toUpperCase();
  const { data, error, mutate } = useSWR<SecurityListItem[]>("/api/securities");
  const [importOpen, setImportOpen] = React.useState(false);

  if (ticker) return <TickerView ticker={ticker} />;

  return (
    <div>
      <PageHeader
        title="Prices"
        subtitle="End-of-day closes you imported. Never real-time."
        action={
          <Button size="sm" onClick={() => setImportOpen(true)}>
            <Upload /> Import
          </Button>
        }
      />
      <ErrorNote error={error} />
      {!data && !error && <Skeleton className="h-40" />}
      {data?.length === 0 && (
        <EmptyState icon={LineChart} title="No securities yet">
          Add one to a watchlist, record a transaction, or import a price CSV.
        </EmptyState>
      )}
      {!!data?.length && (
        <div className="overflow-hidden rounded-2xl border border-border/60 bg-card">
          <ul className="divide-y divide-border/60">
            {data.map((x) => (
              <li key={x.ticker}>
                <SecurityRow security={x} sub={x.bars ? `${x.name !== x.ticker ? `${x.name} · ` : ""}${fmtInt(x.bars)} days` : "No prices"} quote={<QuoteCell quote={x.quote} />} />
              </li>
            ))}
          </ul>
        </div>
      )}
      <FxSection />
      <ImportPricesSheet
        key={importOpen ? "open" : "closed"}
        open={importOpen}
        onOpenChange={setImportOpen}
        onDone={(t) => {
          mutate();
          router.replace(`/prices?t=${encodeURIComponent(t)}`);
        }}
      />
    </div>
  );
}
