"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { SourceLine } from "@/components/page";
import { fmtDate, fmtPct, signClass } from "@/lib/format";
import type { Fx, FxRate } from "@/lib/types";
import { cn } from "@/lib/utils";

const LineMini = dynamic(() => import("@/components/charts/line-mini"), { ssr: false, loading: () => <Skeleton className="h-40" /> });

function digits(v: number) {
  return v >= 100 ? 2 : 4;
}

export function FxCard() {
  const { data } = useSWR<Fx>("/api/fx", { revalidateOnFocus: false });
  const [open, setOpen] = React.useState<FxRate | null>(null);
  const { data: hist } = useSWR<{ points: { date: string; value: string }[] }>(open ? `/api/fx/${open.currency}` : null);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Euro reference rates</CardTitle>
        {data && (data.status === "ok" ? <Badge variant="muted">ECB · {data.rates[0] ? fmtDate(data.rates[0].date) : "—"}</Badge> : <Badge variant="negative">Unavailable</Badge>)}
      </CardHeader>
      <CardContent>
        {!data && <Skeleton className="h-20" />}
        {data && data.rates.length === 0 && (
          <p className="text-[13px] text-muted-foreground">{data.message || "No rates downloaded yet."}</p>
        )}
        {data && data.rates.length > 0 && (
          <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 pb-1">
            {data.rates.map((r) => (
              <button key={r.currency} onClick={() => setOpen(r)} className="min-w-[96px] shrink-0 rounded-xl bg-elevated px-3 py-2 text-left active:scale-[0.97]">
                <p className="text-[11px] font-semibold text-muted-foreground">EUR/{r.currency}</p>
                <p className="num text-[15px] font-semibold">{Number(r.value).toFixed(digits(Number(r.value)))}</p>
                <p className={cn("num text-[11px] font-medium", signClass(r.change_pct))}>{fmtPct(r.change_pct)}</p>
              </button>
            ))}
          </div>
        )}
        {data && (
          <SourceLine>
            Source: {data.source} (reuse permitted with attribution). {data.note}
            {data.status === "error" && data.message ? ` Last update failed: ${data.message}` : ""}
          </SourceLine>
        )}
      </CardContent>

      <Sheet open={!!open} onOpenChange={(o) => !o && setOpen(null)}>
        {open && (
          <SheetContent title={`EUR/${open.currency}`} description={`1 EUR in ${open.currency} · ECB reference rate`}>
            <div className="px-4 pb-6">
              <p className="num text-3xl font-bold">{Number(open.value).toFixed(digits(Number(open.value)))}</p>
              <p className="mb-3 text-[12px] text-muted-foreground">
                {fmtDate(open.date)} · change vs previous fixing {fmtPct(open.change_pct)}
              </p>
              {hist ? (
                <LineMini points={hist.points.map((p) => ({ date: p.date, value: Number(p.value) }))} digits={digits(Number(open.value))} />
              ) : (
                <Skeleton className="h-40" />
              )}
              <SourceLine>Stored history only ({hist?.points.length ?? 0} fixings). Not a trading rate.</SourceLine>
            </div>
          </SheetContent>
        )}
      </Sheet>
    </Card>
  );
}
