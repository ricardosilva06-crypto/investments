"use client";

import * as React from "react";
import useSWR from "swr";
import { LineChart, Loader2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ErrorNote } from "@/components/page";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";

type Status = { provider: string | null; usage: { hour: number; day: number; hour_limit: number; day_limit: number } };

export function PriceImportCard() {
  const { data: status } = useSWR<Status>("/api/admin/prices/status");
  const [ticker, setTicker] = React.useState("");
  const [currency, setCurrency] = React.useState("USD");
  const [source, setSource] = React.useState("");
  const [file, setFile] = React.useState<File | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);
  const [result, setResult] = React.useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    if (file.size > 5_000_000) return setError(new Error("File is larger than 5 MB."));
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r = await api<{ ticker: string; imported: number; first: string; last: string }>(
        `/api/admin/prices/${encodeURIComponent(ticker.trim().toUpperCase())}/import`,
        { method: "POST", json: { csv: await file.text(), source, currency } },
      );
      setResult(`Imported ${r.imported} daily bars for ${r.ticker} (latest ${fmtDate(r.last)}).`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card id="prices">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <LineChart className="size-4" /> End-of-day prices
        </CardTitle>
        {status &&
          (status.provider ? (
            <Badge variant="positive">{status.provider}</Badge>
          ) : (
            <Badge variant="muted">CSV only</Badge>
          ))}
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-[13px] text-muted-foreground">
          {status?.provider
            ? `Automatic refresh via ${status.provider} (free plan): ${status.usage.hour}/${status.usage.hour_limit} requests this hour, ${status.usage.day}/${status.usage.day_limit} in 24 h.`
            : "No automatic provider configured (optional: set II_TIINGO_API_KEY). You can import daily prices from a CSV, e.g. exported from your broker."}
        </p>
        <form onSubmit={submit} className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Symbol" htmlFor="pt">
              <Input id="pt" value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} placeholder="AAPL" required maxLength={20} autoCapitalize="characters" autoCorrect="off" />
            </Field>
            <Field label="Currency" htmlFor="pc">
              <NativeSelect id="pc" value={currency} onChange={(e) => setCurrency(e.target.value)}>
                {["USD", "EUR", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN", "JPY", "CAD", "AUD", "BRL"].map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </NativeSelect>
            </Field>
          </div>
          <Field label="Where is this data from?" htmlFor="ps">
            <Input id="ps" value={source} onChange={(e) => setSource(e.target.value)} placeholder="e.g. My broker export" required minLength={2} maxLength={48} />
          </Field>
          <Field label="CSV file (header with Date and Close; Open/High/Low/Volume optional)" htmlFor="pf">
            <Input id="pf" type="file" accept=".csv,text/csv,text/plain" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required className="py-2" />
          </Field>
          <ErrorNote error={error} />
          {result && <p className="text-[13px] text-positive">{result}</p>}
          <Button type="submit" variant="secondary" className="w-full" disabled={busy || !file}>
            {busy ? <Loader2 className="animate-spin" /> : <Upload />} Import prices
          </Button>
        </form>
        <p className="text-[11.5px] text-muted-foreground">
          Only import data you are allowed to use. Imported bars are shared with all members and labelled with the source you enter.
        </p>
      </CardContent>
    </Card>
  );
}
