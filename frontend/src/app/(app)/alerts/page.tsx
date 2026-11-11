"use client";

import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { BellPlus, BellRing, FileText, Loader2, Smartphone, Trash2, TrendingDown, TrendingUp, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorNote, PageHeader, SourceLine } from "@/components/page";
import { api } from "@/lib/api";
import { fmtRelative } from "@/lib/format";
import { currentSubscription, disablePush, enablePush, pushSupported } from "@/lib/push";
import type { AlertItem } from "@/lib/types";
import { cn } from "@/lib/utils";

const KIND = {
  price_above: { label: "Close at or above", icon: TrendingUp },
  price_below: { label: "Close at or below", icon: TrendingDown },
  daily_move: { label: "Daily move of at least", icon: Zap },
  filing: { label: "New SEC filing", icon: FileText },
} as const;

function describe(a: AlertItem) {
  if (a.kind === "filing") return a.forms ? `Forms: ${a.forms}` : "Any form";
  if (a.kind === "daily_move") return `±${(Number(a.threshold) * 100).toFixed(1)}% vs previous close`;
  return `${Number(a.threshold)}`;
}

function PushCard() {
  const supported = pushSupported();
  const [on, setOn] = React.useState<boolean | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);
  const [msg, setMsg] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!supported) return;
    currentSubscription().then((s) => setOn(!!s));
  }, [supported]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Smartphone className="size-4" /> Push notifications
        </CardTitle>
        {on && <Badge variant="positive">On for this device</Badge>}
      </CardHeader>
      <CardContent className="space-y-2">
        {!supported ? (
          <p className="text-[13px] text-muted-foreground">
            Not available here. Push needs HTTPS, and on iPhone the app installed to the home screen (iOS 16.4+). Alerts still appear in the bell menu.
          </p>
        ) : (
          <>
            <p className="text-[13px] text-muted-foreground">
              Optional. Uses the free Web Push standard: the encrypted message is relayed by your browser maker’s push service. In-app notifications always work.
            </p>
            <div className="grid grid-cols-2 gap-2">
              <Button
                variant={on ? "secondary" : "default"}
                disabled={busy || on === null}
                onClick={async () => {
                  setBusy(true);
                  setError(null);
                  setMsg(null);
                  try {
                    if (on) await disablePush();
                    else await enablePush();
                    setOn(!on);
                  } catch (e) {
                    setError(e);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {busy && <Loader2 className="animate-spin" />} {on ? "Turn off" : "Turn on"}
              </Button>
              <Button
                variant="secondary"
                disabled={!on || busy}
                onClick={async () => {
                  const r = await api<{ sent: number }>("/api/push/test", { method: "POST" }).catch((e) => (setError(e), null));
                  if (r) setMsg(r.sent ? "Test sent. It should arrive in a few seconds." : "No device received it.");
                }}
              >
                Send test
              </Button>
            </div>
          </>
        )}
        <ErrorNote error={error} />
        {msg && <p className="text-[12px] text-muted-foreground">{msg}</p>}
      </CardContent>
    </Card>
  );
}

function NewAlertSheet({ open, onOpenChange, initialTicker, onDone }: { open: boolean; onOpenChange: (o: boolean) => void; initialTicker: string; onDone: () => void }) {
  const [ticker, setTicker] = React.useState(initialTicker);
  const [kind, setKind] = React.useState<AlertItem["kind"]>("price_above");
  const [value, setValue] = React.useState("");
  const [forms, setForms] = React.useState("10-K,10-Q,8-K");
  const [repeat, setRepeat] = React.useState(false);
  const [note, setNote] = React.useState("");
  const [error, setError] = React.useState<unknown>(null);
  const [busy, setBusy] = React.useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const n = value.replace(",", ".");
    try {
      await api("/api/alerts", {
        method: "POST",
        json: { ticker, kind, threshold: kind === "filing" ? null : kind === "daily_move" ? String(Number(n) / 100) : n, forms: kind === "filing" ? forms : "", repeat, note },
      });
      setValue("");
      setNote("");
      onDone();
      onOpenChange(false);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent title="New alert" description="Checked against stored end-of-day data and SEC filings">
        <form onSubmit={submit} className="space-y-3 px-4 pb-6">
          <Field label="Ticker" htmlFor="at">
            <Input id="at" value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} required maxLength={20} autoCapitalize="characters" autoCorrect="off" />
          </Field>
          <Field label="Condition" htmlFor="ak">
            <NativeSelect id="ak" value={kind} onChange={(e) => setKind(e.target.value as AlertItem["kind"])}>
              {Object.entries(KIND).map(([k, v]) => (
                <option key={k} value={k}>
                  {v.label}
                </option>
              ))}
            </NativeSelect>
          </Field>
          {kind === "filing" ? (
            <Field label="Form types (comma separated, empty = any)" htmlFor="af">
              <Input id="af" value={forms} onChange={(e) => setForms(e.target.value.toUpperCase())} maxLength={80} />
            </Field>
          ) : (
            <Field label={kind === "daily_move" ? "Move (%)" : "Price level (in the price’s currency)"} htmlFor="av">
              <Input id="av" inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} required placeholder={kind === "daily_move" ? "5" : "150.00"} />
            </Field>
          )}
          <Field label="Note (optional)" htmlFor="an">
            <Input id="an" value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} placeholder="e.g. revisit thesis" />
          </Field>
          <label className="flex items-center gap-2 text-[14px]">
            <input type="checkbox" checked={repeat} onChange={(e) => setRepeat(e.target.checked)} className="size-4 accent-[var(--primary)]" />
            Keep active after it triggers
          </label>
          <ErrorNote error={error} />
          <Button type="submit" className="w-full" disabled={busy}>
            Create alert
          </Button>
          <p className="text-[12px] text-muted-foreground">
            Prices are end-of-day closes, so alerts fire after new closes are stored (daily refresh or import), never intraday.
          </p>
        </form>
      </SheetContent>
    </Sheet>
  );
}

export default function AlertsPage() {
  const params = useSearchParams();
  const preset = (params.get("t") ?? "").toUpperCase();
  const { data, error, mutate } = useSWR<AlertItem[]>("/api/alerts");
  const [open, setOpen] = React.useState(!!preset);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Alerts"
        subtitle="Private to you"
        action={
          <Button size="sm" onClick={() => setOpen(true)}>
            <BellPlus /> New
          </Button>
        }
      />
      <ErrorNote error={error} />
      {!data && !error && <Skeleton className="h-32" />}
      {data?.length === 0 && (
        <EmptyState icon={BellRing} title="No alerts yet">
          Get notified when a stored close crosses a level, a stock moves sharply, or a company files with the SEC.
        </EmptyState>
      )}
      <ul className="space-y-2">
        {data?.map((a) => {
          const K = KIND[a.kind];
          return (
            <li key={a.id} className={cn("rounded-2xl border border-border/60 bg-card p-3.5", !a.active && "opacity-60")}>
              <div className="flex items-center gap-3">
                <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent text-accent-foreground">
                  <K.icon className="size-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="font-semibold">
                    <Link href={`/company?t=${a.ticker}`}>{a.ticker}</Link> <span className="font-normal text-muted-foreground">· {K.label}</span>
                  </p>
                  <p className="num text-[13px]">{describe(a)}</p>
                  <p className="text-[11px] text-muted-foreground">
                    {a.last_triggered_at ? `Triggered ${fmtRelative(a.last_triggered_at)}` : "Not triggered yet"}
                    {a.repeat ? " · repeats" : " · one-shot"}
                    {a.note ? ` · ${a.note}` : ""}
                  </p>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <button
                    role="switch"
                    aria-checked={a.active}
                    aria-label={a.active ? "Pause alert" : "Activate alert"}
                    onClick={async () => {
                      await api(`/api/alerts/${a.id}`, { method: "PATCH", json: { active: !a.active } });
                      mutate();
                    }}
                    className={cn("relative h-6 w-10 rounded-full transition", a.active ? "bg-primary" : "bg-muted")}
                  >
                    <span className={cn("absolute top-0.5 size-5 rounded-full bg-white shadow transition-all", a.active ? "left-[18px]" : "left-0.5")} />
                  </button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-8"
                    aria-label="Delete alert"
                    onClick={async () => {
                      await api(`/api/alerts/${a.id}`, { method: "DELETE" });
                      mutate();
                    }}
                  >
                    <Trash2 className="size-4 text-muted-foreground" />
                  </Button>
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      <PushCard />
      <SourceLine>Alerts are evaluated after each daily refresh, price import or company page refresh. They appear in the bell menu.</SourceLine>
      <NewAlertSheet open={open} onOpenChange={setOpen} initialTicker={preset} onDone={() => mutate()} />
    </div>
  );
}
