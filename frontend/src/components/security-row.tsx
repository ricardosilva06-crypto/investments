import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { fmtPct, fmtPrice, fmtShortDate } from "@/lib/format";
import type { Quote, Security } from "@/lib/types";
import { cn } from "@/lib/utils";

export function TickerAvatar({ ticker }: { ticker: string }) {
  return (
    <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-elevated text-[11px] font-bold tracking-tight text-foreground ring-1 ring-border/70">
      {ticker.replace(/[^A-Z0-9]/g, "").slice(0, 4)}
    </span>
  );
}

export function SecurityRow({ security, right, sub, quote }: { security: Security; right?: React.ReactNode; sub?: React.ReactNode; quote?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 px-3.5 py-3">
      <Link href={`/prices?t=${encodeURIComponent(security.ticker)}`} className="flex min-w-0 flex-1 items-center gap-3 active:opacity-70">
        <TickerAvatar ticker={security.ticker} />
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5">
            <span className="font-semibold">{security.ticker}</span>
            {security.exchange && <span className="text-[11px] text-muted-foreground">{security.exchange}</span>}
          </span>
          <span className="block truncate text-[13px] text-muted-foreground">{sub ?? security.name}</span>
        </span>
        {quote}
        {!right && !quote && <ChevronRight className="size-4 shrink-0 text-muted-foreground" />}
      </Link>
      {right}
    </div>
  );
}

/** Last stored end-of-day close with its date. Shows "No price" rather than anything estimated. */
export function QuoteCell({ quote }: { quote: Quote | null | undefined }) {
  if (!quote) return <span className="shrink-0 text-right text-[12px] text-muted-foreground">No price</span>;
  const pct = quote.change_pct === null ? null : Number(quote.change_pct);
  return (
    <span className="num shrink-0 text-right">
      <span className="block text-[14px] font-semibold">{fmtPrice(quote.close, quote.currency)}</span>
      <span className="flex items-center justify-end gap-1 text-[11px]">
        <span className="text-muted-foreground">{fmtShortDate(quote.date)}</span>
        {pct !== null && (
          <span className={cn("rounded px-1 font-semibold", pct >= 0 ? "bg-positive/15 text-positive" : "bg-negative/15 text-negative")}>{fmtPct(pct)}</span>
        )}
      </span>
    </span>
  );
}
