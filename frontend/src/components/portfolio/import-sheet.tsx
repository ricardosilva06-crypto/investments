"use client";

import * as React from "react";
import { Loader2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { ErrorNote } from "@/components/page";
import { api } from "@/lib/api";

export function ImportSheet({ pid, open, onOpenChange, onDone }: { pid: number; open: boolean; onOpenChange: (o: boolean) => void; onDone: () => void }) {
  const [file, setFile] = React.useState<File | null>(null);
  const [ccy, setCcy] = React.useState("EUR");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);
  const [msg, setMsg] = React.useState<string | null>(null);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const r = await api<{ imported: number }>(`/api/portfolios/${pid}/import`, { method: "POST", json: { csv: await file.text(), default_currency: ccy } });
      setMsg(`Imported ${r.imported} transactions.`);
      onDone();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent title="Import transactions" description="CSV with a header row; all rows or nothing">
        <form onSubmit={submit} className="space-y-3 px-4 pb-6">
          <div className="rounded-xl bg-elevated p-3 font-mono text-[11.5px] leading-relaxed text-muted-foreground">
            Date;Symbol;Type;Quantity;Price;Fees;Currency
            <br />
            2024-01-02;ASML.AS;Buy;2;600,50;1,50;EUR
            <br />
            2024-03-01;ASML.AS;Dividend;0;3,20;0;EUR
          </div>
          <p className="text-[12px] text-muted-foreground">
            Type: buy, sell or dividend (amount in Price). Comma or semicolon separated; decimal commas accepted. Ambiguous numbers like “1,234” are rejected. Duplicates are not detected: import each file once.
          </p>
          <Input type="file" accept=".csv,text/csv,text/plain" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required className="py-2" aria-label="CSV file" />
          <Field label="Currency when the file has no currency column" htmlFor="icc">
            <NativeSelect id="icc" value={ccy} onChange={(e) => setCcy(e.target.value)}>
              {["EUR", "USD", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN", "JPY", "CAD", "AUD", "BRL"].map((c) => (
                <option key={c}>{c}</option>
              ))}
            </NativeSelect>
          </Field>
          <ErrorNote error={error} />
          {msg && <p className="text-[13px] text-positive">{msg}</p>}
          <Button type="submit" className="w-full" disabled={!file || busy}>
            {busy ? <Loader2 className="animate-spin" /> : <Upload />} Import
          </Button>
        </form>
      </SheetContent>
    </Sheet>
  );
}
