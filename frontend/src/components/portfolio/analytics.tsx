"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import useSWR from "swr";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { ErrorNote, SourceLine } from "@/components/page";
import { fmtDate, fmtMoney, fmtPct, signClass } from "@/lib/format";
import type { Analytics } from "@/lib/types";
import { cn } from "@/lib/utils";

const ValueHistory = dynamic(() => import("@/components/charts/value-history"), { ssr: false, loading: () => <Skeleton className="h-52" /> });
const FinancialBars = dynamic(() => import("@/components/charts/financial-bars"), { ssr: false, loading: () => <Skeleton className="h-44" /> });

export function useAnalytics(pid: number, base: string | undefined) {
  return useSWR<Analytics>(`/api/portfolios/${pid}/analytics${base ? `?base=${base}` : ""}`);
}

export function AllocationView({ pid, base }: { pid: number; base?: string }) {
  const { data, error } = useAnalytics(pid, base);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Skeleton className="h-48" />;
  const a = data.allocation;
  if (a.items.length === 0) return <p className="py-6 text-center text-[13px] text-muted-foreground">No open positions.</p>;
  const groups = Object.keys(a.totals);
  const useBase = a.base && !a.base.error && a.base.total;
  return (
    <div className="space-y-3">
      {a.base &&
        (a.base.error ? (
          <p className="rounded-xl bg-elevated px-3 py-2 text-[12px] text-muted-foreground">{a.base.error}</p>
        ) : (
          <div className="rounded-2xl border border-border/60 bg-card p-3.5">
            <p className="text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">Total in {a.base.currency}</p>
            <p className="num text-[26px] font-bold">{fmtMoney(a.base.total, a.base.currency)}</p>
            <p className="text-[12px] text-muted-foreground">
              Converted at ECB reference rates of {fmtDate(a.base.rate_date)}. {a.base.includes_cost_basis && "Includes cost basis for positions without a stored price."}
            </p>
          </div>
        ))}
      {(useBase ? ["__all"] : groups).map((g) => {
        const items = useBase ? a.items : a.items.filter((i) => i.currency === g);
        const sorted = [...items].sort((x, y) => Number(useBase ? y.weight_total : y.weight_in_currency) - Number(useBase ? x.weight_total : x.weight_in_currency));
        return (
          <div key={g} className="rounded-2xl border border-border/60 bg-card p-3.5">
            <p className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
              {useBase ? `All positions, weights in ${a.base!.currency}` : `${g} positions · ${fmtMoney(a.totals[g], g)}`}
            </p>
            <ul className="space-y-2">
              {sorted.map((i) => {
                const w = Number(useBase ? i.weight_total : i.weight_in_currency) || 0;
                return (
                  <li key={`${i.symbol}-${i.currency}`}>
                    <div className="flex items-baseline justify-between text-[13px]">
                      <span className="font-semibold">
                        {i.symbol} {i.basis === "cost" && <Badge variant="muted">cost basis</Badge>}
                      </span>
                      <span className="num">
                        {(w * 100).toFixed(1)}% <span className="text-muted-foreground">· {fmtMoney(i.value, i.currency)}</span>
                      </span>
                    </div>
                    <div className="mt-1 h-2 overflow-hidden rounded-full bg-muted">
                      <div className={cn("h-full rounded-full", i.basis === "cost" ? "bg-primary/40" : "bg-primary")} style={{ width: `${Math.max(1, w * 100)}%` }} />
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
      <SourceLine>Weights use market value at the latest stored close where available, otherwise cost basis (lighter bar).</SourceLine>
    </div>
  );
}

export function PerformanceView({ pid }: { pid: number }) {
  const { data, error } = useAnalytics(pid, undefined);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Skeleton className="h-56" />;
  const entries = Object.entries(data.history);
  if (entries.length === 0)
    return (
      <p className="rounded-2xl border border-dashed border-border p-4 text-center text-[13px] text-muted-foreground">
        No value history yet. It needs stored end-of-day prices for the symbols you hold (import them in Administration).
      </p>
    );
  return (
    <div className="space-y-3">
      {entries.map(([ccy, pts]) => {
        const valued = pts.filter((p) => p.value !== null);
        const last = valued[valued.length - 1];
        const gain = last ? Number(last.value) - Number(last.cost) : null;
        return (
          <div key={ccy} className="rounded-2xl border border-border/60 bg-card p-3">
            <div className="mb-1 flex items-baseline justify-between">
              <p className="font-semibold">{ccy} holdings</p>
              {last && (
                <p className="num text-[13px]">
                  {fmtMoney(last.value, ccy)}{" "}
                  <span className={cn("font-semibold", signClass(gain))}>
                    ({gain! >= 0 ? "+" : ""}
                    {fmtMoney(gain, ccy)} · {fmtPct(Number(last.cost) ? gain! / Number(last.cost) : null, 1)})
                  </span>
                </p>
              )}
            </div>
            <ValueHistory points={pts.map((p) => ({ date: p.date, value: p.value === null ? null : Number(p.value), cost: Number(p.cost) }))} currency={ccy} />
            {last && <p className="text-[11px] text-muted-foreground">Latest valued day {fmtDate(last.date)} · unrealised vs current cost basis</p>}
          </div>
        );
      })}
      <SourceLine>{data.history_note} Not a time-weighted return: deposits (new buys) raise the value too.</SourceLine>
    </div>
  );
}

export function DividendsView({ pid }: { pid: number }) {
  const { data, error } = useAnalytics(pid, undefined);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Skeleton className="h-56" />;
  const d = data.dividends;
  const ccys = Object.keys(d.by_year);
  if (ccys.length === 0)
    return (
      <p className="rounded-2xl border border-dashed border-border p-4 text-center text-[13px] text-muted-foreground">
        No dividends recorded. Add a transaction of type “Dividend” with the net amount received.
      </p>
    );
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        {Object.entries(d.ttm_by_currency).map(([c, v]) => (
          <div key={c} className="rounded-2xl border border-border/60 bg-card p-3">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Last 12 months · {c}</p>
            <p className="num text-[20px] font-bold">{fmtMoney(v, c)}</p>
          </div>
        ))}
      </div>
      {Object.entries(d.last_12_months).map(([c, months]) => (
        <div key={c} className="rounded-2xl border border-border/60 bg-card p-3">
          <p className="mb-1 font-semibold">Monthly income · {c}</p>
          <FinancialBars data={months.map((m) => ({ label: m.month.slice(2), value: Number(m.amount), derived: false }))} kind="money" currency={c} title={`Monthly dividends ${c}`} />
        </div>
      ))}
      <div className="rounded-2xl border border-border/60 bg-card p-3">
        <p className="mb-2 font-semibold">By year</p>
        <table className="num w-full text-[13px]">
          <tbody>
            {ccys.flatMap((c) =>
              [...d.by_year[c]].reverse().map((y) => (
                <tr key={`${c}${y.year}`} className="border-t border-border/40">
                  <td className="py-1.5">{y.year}</td>
                  <td className="py-1.5 text-right font-medium">{fmtMoney(y.amount, c)}</td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>
      <ul className="divide-y divide-border/60 overflow-hidden rounded-2xl border border-border/60 bg-card">
        {d.by_symbol.map((s) => (
          <li key={`${s.symbol}${s.currency}`} className="flex items-center gap-3 px-3.5 py-3">
            <div className="min-w-0 flex-1">
              <p className="font-semibold">{s.symbol}</p>
              <p className="text-[12px] text-muted-foreground">
                {s.payments} payments · last {fmtDate(s.last_date)}
              </p>
            </div>
            <div className="num text-right text-[13px]">
              <p className="font-semibold">{fmtMoney(s.ttm, s.currency)} TTM</p>
              <p className="text-[12px] text-muted-foreground">
                {s.yield_on_cost ? `${(Number(s.yield_on_cost) * 100).toFixed(2)}% yield on cost` : `total ${fmtMoney(s.total, s.currency)}`}
              </p>
            </div>
          </li>
        ))}
      </ul>
      <SourceLine>{d.note} Yield on cost = last-12-month dividends ÷ current cost basis (calculated).</SourceLine>
    </div>
  );
}
