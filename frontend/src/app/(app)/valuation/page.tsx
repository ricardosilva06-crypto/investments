"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { AlertTriangle, BookmarkPlus, Info, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorNote, PageHeader, SourceLine } from "@/components/page";
import { api } from "@/lib/api";
import { fmtDate, fmtFinancial, fmtPct, fmtPrice, fmtRelative, signClass } from "@/lib/format";
import type { DcfField, DcfInputs, DcfResult, SavedValuation } from "@/lib/types";
import { cn } from "@/lib/utils";

const FinancialBars = dynamic(() => import("@/components/charts/financial-bars"), { ssr: false, loading: () => <Skeleton className="h-44" /> });

type Unit = "pct" | "millions" | "int" | "plain";
const FIELDS: { key: string; unit: Unit; step?: string }[] = [
  { key: "base_fcf", unit: "millions" },
  { key: "growth_stage1", unit: "pct" },
  { key: "years_stage1", unit: "int" },
  { key: "years_stage2", unit: "int" },
  { key: "terminal_growth", unit: "pct" },
  { key: "discount_rate", unit: "pct" },
  { key: "net_cash", unit: "millions" },
  { key: "shares", unit: "millions" },
];

const KIND_BADGE: Record<DcfField["kind"], { label: string; v: "positive" | "default" | "warning" | "negative" }> = {
  reported: { label: "Reported", v: "positive" },
  calculated: { label: "Calculated", v: "default" },
  assumption: { label: "Assumption", v: "warning" },
  missing: { label: "Missing", v: "negative" },
};

function toDisplay(v: string | number | null, unit: Unit) {
  if (v === null || v === "") return "";
  const n = Number(v);
  if (unit === "pct") return String(+(n * 100).toFixed(2));
  // Keep full precision (small companies can have FCF well below 1 million).
  if (unit === "millions") return String(Number((n / 1e6).toPrecision(10)));
  return String(n);
}
function fromDisplay(v: string, unit: Unit) {
  const n = Number(v.replace(",", "."));
  if (!Number.isFinite(n) || v.trim() === "") return null;
  if (unit === "pct") return String(n / 100);
  if (unit === "millions") return String(n * 1e6);
  if (unit === "int") return Math.round(n);
  return String(n);
}

export default function ValuationPage() {
  const t = (useSearchParams().get("t") ?? "").toUpperCase();
  const { data: base, error } = useSWR<DcfInputs>(t ? `/api/companies/${encodeURIComponent(t)}/dcf-inputs` : null, { revalidateOnFocus: false });
  const { data: saved, mutate: mutateSaved } = useSWR<SavedValuation[]>(t ? `/api/valuations?ticker=${encodeURIComponent(t)}` : null);
  const [vals, setVals] = React.useState<Record<string, string>>({});
  const [loadedFor, setLoadedFor] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<DcfResult | null>(null);
  const [calcError, setCalcError] = React.useState<unknown>(null);
  const [name, setName] = React.useState("");
  const [savedMsg, setSavedMsg] = React.useState<string | null>(null);

  if (base && loadedFor !== base.ticker) {
    setLoadedFor(base.ticker);
    setVals(Object.fromEntries(FIELDS.map((f) => [f.key, toDisplay(base.fields[f.key]?.value ?? null, f.unit)])));
  }

  const body = React.useMemo(() => {
    const b: Record<string, string | number | null> = {};
    for (const f of FIELDS) b[f.key] = fromDisplay(vals[f.key] ?? "", f.unit);
    b.price = base?.price?.close ?? null;
    return b;
  }, [vals, base]);
  const complete = FIELDS.every((f) => body[f.key] !== null);

  React.useEffect(() => {
    if (!complete) return;
    const h = setTimeout(async () => {
      try {
        setResult(await api<DcfResult>("/api/valuation/dcf", { method: "POST", json: body }));
        setCalcError(null);
      } catch (e) {
        setCalcError(e);
        setResult(null);
      }
    }, 300);
    return () => clearTimeout(h);
  }, [body, complete]);

  if (!t) return <ErrorNote error="No ticker given." />;
  if (error) return <ErrorNote error={error} />;
  if (!base) return <Skeleton className="h-96" />;

  const ccy = base.currency;
  const r = result?.result;
  const termShare = r?.terminal_share ? Number(r.terminal_share) : null;

  async function save() {
    try {
      await api("/api/valuations", { method: "POST", json: { ticker: base!.ticker, name, inputs: body } });
      setName("");
      setSavedMsg("Scenario saved.");
      mutateSaved();
    } catch (e) {
      setCalcError(e);
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="DCF valuation"
        subtitle={
          <Link href={`/company?t=${base.ticker}`} className="text-primary">
            {base.ticker} · {base.name}
          </Link>
        }
      />

      <div className="flex gap-2 rounded-xl bg-warning/10 px-3 py-2 text-[12px] text-warning">
        <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
        <span>A DCF result is an estimate driven entirely by your assumptions, not a fact or a price target. Small changes in discount or growth rates move it a lot.</span>
      </div>

      {r && (
        <Card className="bg-gradient-to-br from-primary/15 via-card to-card">
          <CardContent className="pt-4">
            <p className="text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">Estimated value per share</p>
            <p className="num text-[34px] font-bold tracking-tight">{fmtPrice(r.per_share, ccy)}</p>
            {base.price ? (
              <p className="text-[13px]">
                vs stored close {fmtPrice(base.price.close, ccy)} ({fmtDate(base.price.date)}):{" "}
                <span className={cn("num font-semibold", signClass(r.upside))}>{fmtPct(r.upside, 1)}</span>
              </p>
            ) : (
              <p className="text-[12px] text-muted-foreground">No stored price in {ccy} to compare with.</p>
            )}
            <div className="num mt-3 grid grid-cols-2 gap-2 text-[13px]">
              <div>
                <p className="text-muted-foreground">Enterprise value</p>
                <p className="font-semibold">{fmtFinancial(r.enterprise_value, "money", ccy)}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Equity value</p>
                <p className="font-semibold">{fmtFinancial(r.equity_value, "money", ccy)}</p>
              </div>
            </div>
            {termShare !== null && (
              <div className="mt-3">
                <div className="flex h-2.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={`Terminal value is ${(termShare * 100).toFixed(0)}% of enterprise value`}>
                  <div className="bg-primary" style={{ width: `${Math.max(0, Math.min(100, (1 - termShare) * 100))}%` }} />
                  <div className="bg-primary/35" style={{ width: `${Math.max(0, Math.min(100, termShare * 100))}%` }} />
                </div>
                <p className="mt-1 text-[12px] text-muted-foreground">
                  {((1 - termShare) * 100).toFixed(0)}% from projected years · {(termShare * 100).toFixed(0)}% from terminal value
                  {termShare > 0.75 && <span className="text-warning"> (high: the result depends mostly on long-run assumptions)</span>}
                </p>
              </div>
            )}
            {r.warning && <p className="mt-2 text-[12px] text-warning">{r.warning}</p>}
          </CardContent>
        </Card>
      )}
      <ErrorNote error={calcError} />

      <Card>
        <CardHeader>
          <CardTitle>Inputs</CardTitle>
          <span className="text-[11px] text-muted-foreground">{ccy}; money and shares in millions</span>
        </CardHeader>
        <CardContent className="space-y-3">
          {FIELDS.map((f) => {
            const meta = base.fields[f.key];
            return (
              <div key={f.key}>
                <div className="mb-1 flex items-center justify-between gap-2">
                  <label htmlFor={f.key} className="text-[13px] font-medium">
                    {meta?.label} {f.unit === "pct" ? "(%)" : f.unit === "millions" ? "(m)" : ""}
                  </label>
                  {meta && <Badge variant={KIND_BADGE[meta.kind].v}>{KIND_BADGE[meta.kind].label}</Badge>}
                </div>
                <Input
                  id={f.key}
                  inputMode="decimal"
                  value={vals[f.key] ?? ""}
                  onChange={(e) => setVals((v) => ({ ...v, [f.key]: e.target.value }))}
                  className={cn("num", meta?.kind === "missing" && !vals[f.key] && "border-negative")}
                />
                {meta?.source && <p className="mt-0.5 text-[11px] text-muted-foreground">{meta.source}</p>}
              </div>
            );
          })}
          <p className="flex gap-1.5 text-[12px] text-muted-foreground">
            <Info className="mt-0.5 size-3.5 shrink-0" /> Growth fades linearly from the high-growth rate to terminal growth over the fade years. The terminal
            value uses the Gordon growth formula. Net cash excludes leases and other obligations.
          </p>
        </CardContent>
      </Card>

      {base.history.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Historical free cash flow</CardTitle>
          </CardHeader>
          <CardContent>
            <FinancialBars
              data={[...base.history].reverse().map((h) => ({ label: h.end.slice(0, 4), value: Number(h.fcf), derived: true }))}
              kind="money"
              currency={ccy}
              title="Free cash flow"
            />
            <SourceLine>Operating cash flow − capital expenditure per fiscal year (SEC XBRL), calculated.</SourceLine>
          </CardContent>
        </Card>
      )}

      {r && result && (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Sensitivity (value per share)</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="no-scrollbar overflow-x-auto">
                <table className="num w-full min-w-max text-[12px]">
                  <thead>
                    <tr>
                      <th className="px-1.5 py-1 text-left text-muted-foreground">Discount ↓ / Terminal →</th>
                      {result.sensitivity.terminal_growths.map((g) => (
                        <th key={g} className="px-1.5 py-1 text-right text-muted-foreground">
                          {(Number(g) * 100).toFixed(1)}%
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.sensitivity.discount_rates.map((dr, i) => (
                      <tr key={dr}>
                        <th className="px-1.5 py-1 text-left text-muted-foreground">{(Number(dr) * 100).toFixed(1)}%</th>
                        {result.sensitivity.per_share[i].map((v, j) => (
                          <td key={j} className={cn("rounded px-1.5 py-1 text-right", i === 2 && j === 2 && "bg-primary/20 font-semibold")}>
                            {v === null ? "—" : fmtPrice(v, ccy)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Projection</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="no-scrollbar overflow-x-auto">
                <table className="num w-full min-w-max text-[12px]">
                  <thead>
                    <tr className="text-muted-foreground">
                      <th className="px-1.5 py-1 text-left">Year</th>
                      <th className="px-1.5 py-1 text-right">Growth</th>
                      <th className="px-1.5 py-1 text-right">FCF</th>
                      <th className="px-1.5 py-1 text-right">Discount</th>
                      <th className="px-1.5 py-1 text-right">Present value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.projection.map((p) => (
                      <tr key={p.year} className="border-t border-border/40">
                        <td className="px-1.5 py-1">{p.year}</td>
                        <td className="px-1.5 py-1 text-right">{(Number(p.growth) * 100).toFixed(1)}%</td>
                        <td className="px-1.5 py-1 text-right">{fmtFinancial(p.fcf, "money", ccy)}</td>
                        <td className="px-1.5 py-1 text-right">{Number(p.discount_factor).toFixed(3)}</td>
                        <td className="px-1.5 py-1 text-right">{fmtFinancial(p.pv, "money", ccy)}</td>
                      </tr>
                    ))}
                    <tr className="border-t border-border/60 font-semibold">
                      <td className="px-1.5 py-1" colSpan={2}>
                        Terminal value
                      </td>
                      <td className="px-1.5 py-1 text-right">{fmtFinancial(r.terminal_value, "money", ccy)}</td>
                      <td />
                      <td className="px-1.5 py-1 text-right">{fmtFinancial(r.pv_terminal, "money", ccy)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Save scenario</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <div className="flex gap-2">
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Base case" maxLength={120} />
                <Button onClick={save} className="shrink-0">
                  <BookmarkPlus /> Save
                </Button>
              </div>
              {savedMsg && <p className="text-[12px] text-positive">{savedMsg}</p>}
              <ul className="divide-y divide-border/60">
                {saved?.map((s) => (
                  <li key={s.id} className="flex items-center gap-2 py-2 text-[13px]">
                    <button
                      className="min-w-0 flex-1 text-left"
                      onClick={() => setVals(Object.fromEntries(FIELDS.map((f) => [f.key, toDisplay(s.inputs[f.key] as string, f.unit)])))}
                    >
                      <span className="block truncate font-medium">{s.name}</span>
                      <span className="text-[11px] text-muted-foreground">
                        {fmtPrice(s.summary.per_share, ccy)} per share · {fmtRelative(s.created_at)} · tap to load
                      </span>
                    </button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="Delete scenario"
                      onClick={async () => {
                        await api(`/api/valuations/${s.id}`, { method: "DELETE" });
                        mutateSaved();
                      }}
                    >
                      <Trash2 className="text-muted-foreground" />
                    </Button>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </>
      )}
      <SourceLine>Inputs marked Reported or Calculated come from SEC XBRL filings; Assumptions are yours to change. Not investment advice.</SourceLine>
    </div>
  );
}
