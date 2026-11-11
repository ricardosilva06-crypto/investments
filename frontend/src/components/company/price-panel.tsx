"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import useSWR from "swr";
import { LineChart } from "lucide-react";
import { Segmented } from "@/components/ui/segmented";
import { Skeleton } from "@/components/ui/skeleton";
import { SourceLine } from "@/components/page";
import { useAuth, useTheme } from "@/components/providers";
import { fmtDate, fmtPct, fmtPrice, signClass } from "@/lib/format";
import type { Prices } from "@/lib/types";
import { cn } from "@/lib/utils";

const PriceChart = dynamic(() => import("@/components/charts/price-chart"), { ssr: false, loading: () => <Skeleton className="h-56" /> });

type Range = "1m" | "3m" | "6m" | "1y" | "5y" | "max";

function useIsDark() {
  const { theme } = useTheme();
  return React.useSyncExternalStore(
    (cb) => {
      const obs = new MutationObserver(cb);
      obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
      return () => obs.disconnect();
    },
    () => document.documentElement.classList.contains("dark"),
    () => theme !== "light",
  );
}

export function PricePanel({ ticker }: { ticker: string }) {
  const { user } = useAuth();
  const [range, setRange] = React.useState<Range>("1y");
  const [mode, setMode] = React.useState<"area" | "candles">("area");
  const { data, isLoading } = useSWR<Prices>(`/api/prices/${encodeURIComponent(ticker)}?range=${range}`);
  const dark = useIsDark();

  if (isLoading && !data) return <Skeleton className="h-72" />;
  if (!data) return null;

  if (data.bars.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-border px-5 py-6 text-center">
        <LineChart className="size-5 text-muted-foreground" />
        <p className="font-semibold">No price history stored</p>
        <p className="text-[13px] text-muted-foreground">
          {data.error
            ? data.error
            : data.provider_configured
              ? "The price provider returned no data for this symbol."
              : "No free price provider is configured."}{" "}
          {user?.role === "admin" ? (
            <>
              Import an end-of-day CSV in{" "}
              <Link href="/admin#prices" className="font-medium text-primary">
                Administration
              </Link>
              .
            </>
          ) : (
            "An administrator can import end-of-day prices."
          )}
        </p>
      </div>
    );
  }

  const first = Number(data.bars[0].close);
  const last = Number(data.bars[data.bars.length - 1].close);
  const change = first ? last / first - 1 : null;
  const hasOhlc = data.bars.every((b) => b.open && b.high && b.low);

  return (
    <div className="rounded-2xl border border-border/60 bg-card p-3">
      <div className="mb-2 grid grid-cols-6 gap-1" role="tablist" aria-label="Range">
        {(["1m", "3m", "6m", "1y", "5y", "max"] as Range[]).map((r) => (
          <button
            key={r}
            role="tab"
            aria-selected={range === r}
            onClick={() => setRange(r)}
            className={cn("rounded-lg py-1.5 text-[12px] font-semibold uppercase text-muted-foreground", range === r && "bg-elevated text-foreground")}
          >
            {r}
          </button>
        ))}
      </div>
      <PriceChart bars={data.bars} mode={mode} dark={dark} />
      <div className="mt-2 flex items-center justify-between gap-2 text-[12px]">
        <span className="min-w-0">
          <span className={cn("num block font-semibold", signClass(change))}>
            {fmtPct(change)} · {fmtPrice(last, data.currency ?? "USD")}
          </span>
          <span className="text-muted-foreground">
            {fmtDate(data.bars[0].date)} → {fmtDate(data.last_date)}
          </span>
        </span>
        {hasOhlc && (
          <Segmented
            className="w-32 shrink-0"
            value={mode}
            onChange={setMode}
            options={[
              { value: "area", label: "Line" },
              { value: "candles", label: "OHLC" },
            ]}
          />
        )}
      </div>
      <SourceLine>
        {data.note} Source: {data.sources.join(", ")}. {data.error ? `Last refresh failed: ${data.error}` : ""}
      </SourceLine>
    </div>
  );
}
