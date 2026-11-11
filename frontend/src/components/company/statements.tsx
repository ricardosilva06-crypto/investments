"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import useSWR from "swr";
import { Segmented } from "@/components/ui/segmented";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorNote, SourceLine } from "@/components/page";
import { fmtDate, fmtFinancial } from "@/lib/format";
import type { Statement } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ProvenanceSheet, type Provenance } from "./provenance-sheet";

const FinancialBars = dynamic(() => import("@/components/charts/financial-bars"), {
  ssr: false,
  loading: () => <Skeleton className="h-44" />,
});

type Kind = Statement["statement"];
type Period = Statement["period"];

export function Statements({ ticker }: { ticker: string }) {
  const [statement, setStatement] = React.useState<Kind>("income");
  const [period, setPeriod] = React.useState<Period>("annual");
  const [selected, setSelected] = React.useState<string | null>(null);
  const [prov, setProv] = React.useState<Provenance | null>(null);
  const { data, error, isLoading } = useSWR<Statement>(
    `/api/companies/${encodeURIComponent(ticker)}/financials?statement=${statement}&period=${period}`,
  );

  const rowKey = data?.rows.find((r) => r.key === selected)?.key ?? data?.rows[0]?.key;
  const row = data?.rows.find((r) => r.key === rowKey);
  const chartData = row && data ? [...data.periods].map((p, i) => ({ label: p.label.replace("FY · ", ""), value: row.values[i] ? Number(row.values[i]!.value) : null, derived: !!row.values[i]?.derived })).reverse() : [];

  return (
    <div>
      <Segmented
        value={statement}
        onChange={(v) => {
          setStatement(v);
          setSelected(null);
        }}
        options={[
          { value: "income", label: "Income" },
          { value: "balance", label: "Balance" },
          { value: "cashflow", label: "Cash flow" },
          { value: "metrics", label: "Ratios" },
        ]}
      />
      <Segmented
        className="mt-2"
        value={period}
        onChange={setPeriod}
        options={[
          { value: "annual", label: "Annual" },
          { value: "quarterly", label: "Quarterly" },
        ]}
      />
      <ErrorNote error={error} />
      {isLoading && !data && <Skeleton className="mt-3 h-64" />}

      {data && data.rows.length === 0 && (
        <p className="mt-4 rounded-2xl border border-dashed border-border p-4 text-center text-[13px] text-muted-foreground">
          No {period} figures available for this statement in the company’s XBRL filings.
        </p>
      )}

      {data && row && (
        <>
          <div className="mt-3 rounded-2xl border border-border/60 bg-card p-3">
            <div className="mb-1 flex items-baseline justify-between gap-2">
              <p className="font-semibold">{row.label}</p>
              <p className="text-[11px] text-muted-foreground">{data.currency} · tap a row to chart it</p>
            </div>
            <FinancialBars data={chartData} kind={row.kind} currency={data.currency} title={row.label} />
          </div>

          <div className="mt-3 overflow-hidden rounded-2xl border border-border/60 bg-card">
            <div className="no-scrollbar overflow-x-auto">
              <table className="num w-max min-w-full border-separate border-spacing-0 text-[13px]">
                <thead>
                  <tr>
                    <th className="sticky left-0 z-10 bg-card px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                      {data.currency}
                    </th>
                    {data.periods.map((p) => (
                      <th key={p.end} className="px-3 py-2.5 text-right text-[11px] font-semibold whitespace-nowrap text-muted-foreground">
                        {p.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((r) => (
                    <tr key={r.key} className={cn(r.key === rowKey && "bg-accent/40")}>
                      <th
                        scope="row"
                        onClick={() => setSelected(r.key)}
                        className={cn(
                          "sticky left-0 z-10 max-w-[150px] cursor-pointer border-t border-border/50 px-3 py-2.5 text-left font-medium",
                          r.key === rowKey ? "bg-accent" : "bg-card",
                          r.indent ? "pl-6 font-normal text-muted-foreground" : "",
                        )}
                      >
                        <span className="line-clamp-2">{r.label}</span>
                      </th>
                      {r.values.map((c, i) => (
                        <td key={i} className="border-t border-border/50 p-0 text-right whitespace-nowrap">
                          {c ? (
                            <button
                              className="w-full px-3 py-2.5 text-right active:bg-muted"
                              onClick={() =>
                                setProv({ label: r.label, period: `${data.periods[i].label} (period ending ${fmtDate(data.periods[i].end)})`, kind: r.kind, currency: data.currency, cell: c })
                              }
                            >
                              {fmtFinancial(c.value, r.kind, data.currency)}
                              {c.derived && <sup className="ml-0.5 text-warning" aria-label="calculated">c</sup>}
                            </button>
                          ) : (
                            <span className="block px-3 py-2.5 text-muted-foreground">—</span>
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <SourceLine>
            <sup className="text-warning">c</sup> = calculated by this app (tap any value for its source or formula). “—” = not reported; nothing is
            estimated. Source: {data.source.name}
            {data.source.last_success_at ? `, downloaded ${fmtDate(data.source.last_success_at, true)}` : ""}. Periods are labelled by fiscal
            period end date.
          </SourceLine>
        </>
      )}
      <ProvenanceSheet p={prov} onClose={() => setProv(null)} />
    </div>
  );
}
