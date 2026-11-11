"use client";

import { ExternalLink } from "lucide-react";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { fmtDate, fmtFinancial } from "@/lib/format";
import type { FinCell } from "@/lib/types";

export type Provenance = { label: string; period: string; kind: string; currency: string; cell: FinCell };

/** Where a number came from: concept, filing, and whether it was reported or calculated. */
export function ProvenanceSheet({ p, onClose }: { p: Provenance | null; onClose: () => void }) {
  return (
    <Sheet open={!!p} onOpenChange={(o) => !o && onClose()}>
      {p && (
        <SheetContent title={p.label} description={p.period}>
          <div className="space-y-3 px-4 pb-6">
            <div className="flex items-center gap-2">
              <p className="num text-3xl font-bold tracking-tight">{fmtFinancial(p.cell.value, p.kind, p.currency)}</p>
              {p.cell.derived ? <Badge variant="warning">Calculated</Badge> : <Badge variant="positive">Reported</Badge>}
            </div>
            {p.kind === "money" && (
              <p className="num text-[13px] text-muted-foreground">
                Exact: {Number(p.cell.value).toLocaleString()} {p.currency}
              </p>
            )}
            <dl className="divide-y divide-border/60 rounded-2xl border border-border/60 text-[13px]">
              {p.cell.concept && (
                <div className="flex justify-between gap-3 px-3.5 py-2.5">
                  <dt className="text-muted-foreground">XBRL concept</dt>
                  <dd className="break-all text-right font-mono text-[12px]">{p.cell.concept}</dd>
                </div>
              )}
              {p.cell.form && (
                <div className="flex justify-between gap-3 px-3.5 py-2.5">
                  <dt className="text-muted-foreground">Filing</dt>
                  <dd className="text-right">
                    {p.cell.form} · filed {fmtDate(p.cell.filed)}
                  </dd>
                </div>
              )}
              {p.cell.accession && (
                <div className="flex justify-between gap-3 px-3.5 py-2.5">
                  <dt className="text-muted-foreground">Accession</dt>
                  <dd className="font-mono text-[12px]">{p.cell.accession}</dd>
                </div>
              )}
              {p.cell.formula && (
                <div className="px-3.5 py-2.5">
                  <dt className="text-muted-foreground">Calculation</dt>
                  <dd className="mt-0.5">{p.cell.formula}</dd>
                </div>
              )}
            </dl>
            {p.cell.url && (
              <a href={p.cell.url} target="_blank" rel="noreferrer" className="flex items-center justify-between rounded-xl bg-elevated px-3.5 py-3 font-medium active:scale-[0.99]">
                Open the filing on SEC EDGAR <ExternalLink className="size-4 text-muted-foreground" />
              </a>
            )}
            <p className="text-[12px] text-muted-foreground">
              {p.cell.derived
                ? "Calculated by this app from reported figures, using the formula above."
                : "Value as reported in the company's XBRL filing. If the figure was restated later, the most recent filing is used."}
            </p>
          </div>
        </SheetContent>
      )}
    </Sheet>
  );
}
