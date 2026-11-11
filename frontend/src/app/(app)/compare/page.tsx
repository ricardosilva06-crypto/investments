"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { Plus, Scale } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorNote, PageHeader, SourceLine } from "@/components/page";
import { CompanyPicker } from "@/components/ai/context-picker";
import { fmtDate, fmtFinancial, fmtPct, fmtPrice } from "@/lib/format";
import type { CompareResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const CompareLines = dynamic(() => import("@/components/charts/compare-lines"), { ssr: false, loading: () => <Skeleton className="h-56" /> });
const DOT = ["bg-[var(--series-1)]", "bg-[var(--series-2)]", "bg-[var(--series-3)]"];

export default function ComparePage() {
  const router = useRouter();
  const params = useSearchParams();
  const tickers = (params.get("t") ?? "").split(",").map((t) => t.trim().toUpperCase()).filter(Boolean).slice(0, 3);
  const [picker, setPicker] = React.useState(false);
  const [metric, setMetric] = React.useState<"revenue" | "net_income" | "fcf">("revenue");
  const { data, error, isLoading } = useSWR<CompareResult>(tickers.length >= 2 ? `/api/compare?tickers=${tickers.join(",")}` : null, { revalidateOnFocus: false });

  const setTickers = (list: string[]) => router.replace(`/compare?t=${list.join(",")}`, { scroll: false });
  const currencies = new Set(data?.companies.map((c) => c.currency).filter(Boolean));
  const sameCcy = currencies.size === 1;
  const years = new Map<string, Record<string, string | number | null>>();
  data?.companies.forEach((c) =>
    c.history.forEach((h) => {
      const y = `FY${h.end.slice(0, 4)}`;
      const row = years.get(y) ?? { year: y };
      row[c.ticker] = h[metric] !== null ? Number(h[metric]) : null;
      years.set(y, row);
    }),
  );
  const chartData = [...years.values()].sort((a, b) => String(a.year).localeCompare(String(b.year)));

  return (
    <div>
      <PageHeader
        title="Compare"
        subtitle="Side by side, from SEC filings"
        action={
          <Button variant="secondary" size="sm" onClick={() => setPicker(true)}>
            <Plus /> Companies
          </Button>
        }
      />
      <div className="mb-3 flex flex-wrap gap-1.5">
        {tickers.map((t, i) => (
          <span key={t} className="flex items-center gap-1.5 rounded-full bg-card px-2.5 py-1 text-[13px] font-semibold ring-1 ring-border">
            <span className={cn("size-2 rounded-full", DOT[i])} />
            {t}
          </span>
        ))}
      </div>

      {tickers.length < 2 && (
        <EmptyState icon={Scale} title="Pick 2 or 3 companies">
          <Button size="sm" className="mt-2" onClick={() => setPicker(true)}>
            Choose companies
          </Button>
        </EmptyState>
      )}
      <ErrorNote error={error} />
      {isLoading && <Skeleton className="h-96" />}

      {data && (
        <>
          <div className="rounded-2xl border border-border/60 bg-card p-3">
            <Segmented
              value={metric}
              onChange={setMetric}
              options={[
                { value: "revenue", label: "Revenue" },
                { value: "net_income", label: "Net income" },
                { value: "fcf", label: "Free cash flow" },
              ]}
            />
            <div className="mt-2">
              {sameCcy && chartData.length > 0 ? (
                <CompareLines data={chartData} series={data.companies.map((c) => c.ticker)} currency={[...currencies][0] as string} />
              ) : (
                <p className="py-8 text-center text-[13px] text-muted-foreground">
                  {sameCcy ? "No annual history available." : "Companies report in different currencies; not plotted on one axis."}
                </p>
              )}
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground">By fiscal year end; fiscal years may end in different months.</p>
          </div>

          <div className="mt-3 overflow-hidden rounded-2xl border border-border/60 bg-card">
            <div className="no-scrollbar overflow-x-auto">
              <table className="num w-full min-w-max border-separate border-spacing-0 text-[13px]">
                <thead>
                  <tr>
                    <th className="sticky left-0 z-10 bg-card px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Latest FY</th>
                    {data.companies.map((c, i) => (
                      <th key={c.ticker} className="px-3 py-2.5 text-right">
                        <Link href={`/company?t=${c.ticker}`} className="inline-flex items-center gap-1.5 font-semibold">
                          <span className={cn("size-2 rounded-full", DOT[i])} />
                          {c.ticker}
                        </Link>
                        <p className="text-[10.5px] font-normal text-muted-foreground">{c.fiscal_year_end ? fmtDate(c.fiscal_year_end) : "no data"}</p>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.fields.map((f) => (
                    <tr key={f.key}>
                      <th scope="row" className="sticky left-0 z-10 border-t border-border/50 bg-card px-3 py-2 text-left font-medium whitespace-nowrap">
                        {f.label}
                      </th>
                      {data.companies.map((c) => {
                        const cell = c.fields[f.key];
                        return (
                          <td key={c.ticker} className="border-t border-border/50 px-3 py-2 text-right whitespace-nowrap">
                            {cell ? (f.kind === "percent" && f.key.includes("growth") ? fmtPct(cell.value, 1) : fmtFinancial(cell.value, f.kind, c.currency ?? "USD")) : "—"}
                            {cell?.derived && <sup className="ml-0.5 text-warning">c</sup>}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                  <tr>
                    <th scope="row" className="sticky left-0 z-10 border-t border-border/50 bg-card px-3 py-2 text-left font-medium">Last close</th>
                    {data.companies.map((c) => (
                      <td key={c.ticker} className="border-t border-border/50 px-3 py-2 text-right whitespace-nowrap">
                        {c.quote ? (
                          <>
                            {fmtPrice(c.quote.close, c.quote.currency)}
                            <span className="block text-[10.5px] text-muted-foreground">{fmtDate(c.quote.date)}</span>
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <th scope="row" className="sticky left-0 z-10 border-t border-border/50 bg-card px-3 py-2 text-left font-medium">
                      P/E <sup className="text-warning">c</sup>
                    </th>
                    {data.companies.map((c) => (
                      <td key={c.ticker} className="border-t border-border/50 px-3 py-2 text-right">
                        {c.pe ? `${Number(c.pe).toFixed(1)}×` : "—"}
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <SourceLine>
            Reported values from SEC XBRL filings; <sup className="text-warning">c</sup> = calculated. P/E = stored end-of-day close ÷ latest fiscal-year diluted EPS.
            Different fiscal year ends and currencies make comparisons approximate.
          </SourceLine>
        </>
      )}

      <CompanyPicker
        open={picker}
        onOpenChange={setPicker}
        selected={tickers}
        onToggle={(t) => setTickers(tickers.includes(t) ? tickers.filter((x) => x !== t) : [...tickers, t].slice(0, 3))}
      />
    </div>
  );
}
