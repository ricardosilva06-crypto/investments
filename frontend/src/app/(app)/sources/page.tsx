"use client";

import useSWR from "swr";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/page";
import { fmtDate, fmtInt } from "@/lib/format";
import type { SystemStatus } from "@/lib/types";

const IN_USE = [
  { name: "SEC EDGAR XBRL company facts", use: "Financial statements & ratios", terms: "Free, official, no key. ≤ 5 requests/s from this app (SEC limit 10/s); each company refreshed at most daily." },
  { name: "SEC EDGAR submissions", use: "Company profile & filing list", terms: "Same policy as above." },
  { name: "ECB Data Portal (EXR)", use: "Euro reference exchange rates", terms: "Free, no key. Reuse permitted with source attribution. Refreshed at most every 6 h." },
  { name: "CSV import (admin)", use: "End-of-day prices", terms: "Your own files; labelled with the source you enter." },
  { name: "Tiingo (optional)", use: "End-of-day prices", terms: "Only if a free API key is configured. Free plan: internal/personal use, hourly and daily limits; this app stays under a fixed budget." },
];

const PLANNED = [
  { name: "FRED (St. Louis Fed)", use: "US macro series (optional)", terms: "Free API key. Some series carry third-party copyright." },
  { name: "Stooq", use: "End-of-day prices (not enabled)", terms: "Now requires a key and has a low daily quota; terms for programmatic use unclear." },
];

export default function SourcesPage() {
  const { data } = useSWR<SystemStatus>("/api/system/status");
  return (
    <div className="space-y-4">
      <PageHeader title="Data sources" subtitle="Every figure in this app shows where it came from and when." />

      <Card>
        <CardHeader>
          <CardTitle>Connected</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {data?.data_sources.length === 0 && <p className="text-[13px] text-muted-foreground">No source has been synced yet.</p>}
          {data?.data_sources.map((s) => (
            <div key={s.source} className="rounded-xl bg-elevated p-3">
              <div className="flex items-center justify-between gap-2">
                <p className="font-semibold">{s.source === "ecb_exr" ? "ECB euro reference rates" : "SEC EDGAR company tickers"}</p>
                <Badge variant={s.status === "ok" ? "positive" : s.status === "error" ? "negative" : "muted"}>{s.status}</Badge>
              </div>
              <p className="mt-1 break-all text-[12px] text-muted-foreground">{s.source_url}</p>
              <p className="mt-1 text-[13px]">
                {fmtInt(s.record_count)} records · last success {s.last_success_at ? fmtDate(s.last_success_at, true) : "never"}
              </p>
              {s.message && <p className="mt-1 text-[12px] text-negative">{s.message}</p>}
              <p className="mt-1 text-[12px] text-muted-foreground">
                {s.source === "ecb_exr"
                  ? "European Central Bank statistics. Free, no key; reuse with attribution."
                  : "Public US government data. Free, no key; requires a declared User-Agent and at most 10 requests per second."}
              </p>
            </div>
          ))}
          <div className="rounded-xl bg-elevated p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="font-semibold">Ollama (local AI)</p>
              <Badge variant={data?.ai.available ? "positive" : "muted"}>{data?.ai.available ? "running" : "offline"}</Badge>
            </div>
            <p className="mt-1 text-[12px] text-muted-foreground">{data?.ai.url} · runs on your own hardware, no data leaves it.</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Per-company and price sources</CardTitle>
        </CardHeader>
        <ul className="divide-y divide-border/60 pb-1">
          {IN_USE.map((p) => (
            <li key={p.name} className="px-4 py-3">
              <p className="font-medium">{p.name}</p>
              <p className="text-[13px] text-muted-foreground">{p.use}</p>
              <p className="text-[12px] text-muted-foreground">{p.terms}</p>
            </li>
          ))}
        </ul>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Not connected</CardTitle>
        </CardHeader>
        <ul className="divide-y divide-border/60 pb-1">
          {PLANNED.map((p) => (
            <li key={p.name} className="px-4 py-3">
              <p className="font-medium">{p.name}</p>
              <p className="text-[13px] text-muted-foreground">{p.use}</p>
              <p className="text-[12px] text-muted-foreground">{p.terms}</p>
            </li>
          ))}
        </ul>
      </Card>
      <p className="text-[12px] text-muted-foreground">
        Market data is never presented as real-time unless the source guarantees it. Missing figures are shown as “—”, never estimated.
      </p>
    </div>
  );
}
