import Link from "next/link";
import { ChevronRight } from "lucide-react";
import type { Security } from "@/lib/types";

export function TickerAvatar({ ticker }: { ticker: string }) {
  return (
    <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-elevated text-[11px] font-bold tracking-tight text-foreground ring-1 ring-border/70">
      {ticker.replace(/[^A-Z0-9]/g, "").slice(0, 4)}
    </span>
  );
}

export function SecurityRow({ security, right, sub }: { security: Security; right?: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 px-3.5 py-3">
      <Link href={`/company?t=${encodeURIComponent(security.ticker)}`} className="flex min-w-0 flex-1 items-center gap-3 active:opacity-70">
        <TickerAvatar ticker={security.ticker} />
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5">
            <span className="font-semibold">{security.ticker}</span>
            {security.exchange && <span className="text-[11px] text-muted-foreground">{security.exchange}</span>}
          </span>
          <span className="block truncate text-[13px] text-muted-foreground">{sub ?? security.name}</span>
        </span>
        {!right && <ChevronRight className="size-4 shrink-0 text-muted-foreground" />}
      </Link>
      {right}
    </div>
  );
}
