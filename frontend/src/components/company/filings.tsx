"use client";

import * as React from "react";
import useSWR from "swr";
import { ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { SourceLine } from "@/components/page";
import { fmtDate } from "@/lib/format";
import type { FilingRow } from "@/lib/types";
import { cn } from "@/lib/utils";

const FILTERS = [
  { v: "key", label: "Key" },
  { v: "10-K,10-K/A,20-F,40-F", label: "Annual" },
  { v: "10-Q,10-Q/A,6-K", label: "Quarterly" },
  { v: "8-K", label: "8-K" },
  { v: "all", label: "All" },
];

export function Filings({ ticker }: { ticker: string }) {
  const [forms, setForms] = React.useState("key");
  const { data } = useSWR<FilingRow[]>(`/api/companies/${encodeURIComponent(ticker)}/filings?forms=${encodeURIComponent(forms)}&limit=60`);
  return (
    <div>
      <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 pb-2">
        {FILTERS.map((f) => (
          <button
            key={f.v}
            onClick={() => setForms(f.v)}
            className={cn(
              "shrink-0 rounded-full border border-border px-3 py-1.5 text-[13px] font-medium",
              forms === f.v ? "border-primary bg-primary text-primary-foreground" : "bg-card text-muted-foreground",
            )}
          >
            {f.label}
          </button>
        ))}
      </div>
      {!data && <Skeleton className="h-48" />}
      {data?.length === 0 && <p className="py-6 text-center text-[13px] text-muted-foreground">No filings of this type in the recent filing index.</p>}
      {!!data?.length && (
        <ul className="divide-y divide-border/60 overflow-hidden rounded-2xl border border-border/60 bg-card">
          {data.map((f) => (
            <li key={f.accession}>
              <a href={f.url} target="_blank" rel="noreferrer" className="flex items-center gap-3 px-3.5 py-3 active:bg-muted">
                <Badge variant={f.form.startsWith("10-K") || f.form.startsWith("20-F") ? "default" : "muted"} className="w-14 justify-center">
                  {f.form}
                </Badge>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px] font-medium">{f.description}</span>
                  <span className="text-[12px] text-muted-foreground">
                    Filed {fmtDate(f.filing_date)}
                    {f.report_date ? ` · period ${fmtDate(f.report_date)}` : ""}
                  </span>
                </span>
                <ExternalLink className="size-4 shrink-0 text-muted-foreground" />
              </a>
            </li>
          ))}
        </ul>
      )}
      <SourceLine>From the SEC EDGAR submissions index (most recent ~1,000 filings). Documents open on sec.gov.</SourceLine>
    </div>
  );
}
