"use client";

import * as React from "react";
import useSWR from "swr";
import { CheckCircle2, Clock, Loader2, Play, ShieldCheck, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { fmtRelative } from "@/lib/format";

type Jobs = { enabled: boolean; jobs: string[]; runs: { id: number; job: string; started_at: string; finished_at: string | null; status: string; message: string }[] };
type Security = { checks: { key: string; ok: boolean; label: string; advice: string }[]; host: string; scheme: string };

const JOB_LABEL: Record<string, string> = {
  daily_refresh: "Daily refresh (SEC data, prices, alerts)",
  feeds: "News feeds (every 30 min)",
  fx: "ECB rates (every 6 h)",
  backup: "Backup (nightly)",
};

export function JobsCard() {
  const { data, mutate } = useSWR<Jobs>("/api/admin/jobs");
  const [busy, setBusy] = React.useState<string | null>(null);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Clock className="size-4" /> Scheduled jobs
        </CardTitle>
        {data && (data.enabled ? <Badge variant="positive">Running</Badge> : <Badge variant="warning">Disabled</Badge>)}
      </CardHeader>
      <CardContent className="space-y-2">
        {data?.jobs.map((j) => {
          const last = data.runs.find((r) => r.job === j);
          return (
            <div key={j} className="flex items-center gap-2 rounded-xl bg-elevated px-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="text-[13px] font-medium">{JOB_LABEL[j] ?? j}</p>
                <p className="truncate text-[11px] text-muted-foreground">
                  {last ? (
                    <>
                      <span className={last.status === "error" ? "text-negative" : ""}>{last.status}</span> · {fmtRelative(last.started_at)}
                      {last.message ? ` · ${last.message}` : ""}
                    </>
                  ) : (
                    "Never run"
                  )}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Run ${j} now`}
                disabled={busy !== null}
                onClick={async () => {
                  setBusy(j);
                  await api(`/api/admin/jobs/${j}/run`, { method: "POST" }).catch(() => {});
                  await mutate();
                  setBusy(null);
                }}
              >
                {busy === j ? <Loader2 className="animate-spin" /> : <Play />}
              </Button>
            </div>
          );
        })}
        <p className="text-[11.5px] text-muted-foreground">Runs inside the server process; no external scheduler or service. Times are UTC (II_DAILY_JOB_HOUR_UTC, II_BACKUP_HOUR_UTC).</p>
      </CardContent>
    </Card>
  );
}

export function SecurityCard() {
  const { data } = useSWR<Security>("/api/admin/security");
  if (!data) return null;
  const bad = data.checks.filter((c) => !c.ok).length;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="size-4" /> Security & remote access
        </CardTitle>
        {bad ? <Badge variant="warning">{bad} to review</Badge> : <Badge variant="positive">All good</Badge>}
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {data.checks.map((c) => (
            <li key={c.key} className="flex gap-2 text-[13px]">
              {c.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-positive" /> : <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" />}
              <span>
                <span className="font-medium">{c.label}</span>
                {!c.ok && <span className="block text-[12px] text-muted-foreground">{c.advice}</span>}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-[11.5px] text-muted-foreground">See README → “Phone access and HTTPS” for the free Tailscale/WireGuard setup.</p>
      </CardContent>
    </Card>
  );
}
