"use client";

import * as React from "react";
import Link from "next/link";
import useSWR from "swr";
import { CloudDownload, ExternalLink, FileUp, Globe2, Link2, Loader2, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorNote, PageHeader, SourceLine } from "@/components/page";
import { useAuth } from "@/components/providers";
import { api } from "@/lib/api";
import { fmtDate, fmtInt, fmtRelative } from "@/lib/format";
import type { EsefCompany } from "@/lib/types";

type UploadResult = { created: boolean; facts: number; skipped_dimensional: number; skipped_other: number; linked_ticker: string | null; filing: { lei: string; entity_name: string; period_end: string } };

function LinkForm({ lei, name, onDone }: { lei: string; name: string; onDone: () => void }) {
  const [ticker, setTicker] = React.useState("");
  const [exchange, setExchange] = React.useState("");
  const [error, setError] = React.useState<unknown>(null);
  return (
    <form
      className="mt-2 space-y-2 rounded-xl bg-elevated p-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        try {
          await api("/api/admin/esef/link", { method: "POST", json: { lei, ticker, name, exchange: exchange || null } });
          onDone();
        } catch (err) {
          setError(err);
        }
      }}
    >
      <p className="text-[13px]">Give it a symbol so it appears in search, watchlists and company pages.</p>
      <div className="grid grid-cols-2 gap-2">
        <Input value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} placeholder="e.g. MC.PA" required maxLength={20} autoCapitalize="characters" aria-label="Ticker" />
        <Input value={exchange} onChange={(e) => setExchange(e.target.value)} placeholder="Exchange (optional)" maxLength={32} aria-label="Exchange" />
      </div>
      <ErrorNote error={error} />
      <Button type="submit" size="sm" className="w-full">
        <Link2 /> Link ticker
      </Button>
    </form>
  );
}

export default function EsefPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const { data, mutate, error } = useSWR<EsefCompany[]>("/api/esef/companies");
  const [file, setFile] = React.useState<File | null>(null);
  const [busy, setBusy] = React.useState<string | null>(null);
  const [opError, setOpError] = React.useState<unknown>(null);
  const [result, setResult] = React.useState<string | null>(null);
  const [lei, setLei] = React.useState("");
  const fileRef = React.useRef<HTMLInputElement>(null);

  async function upload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy("upload");
    setOpError(null);
    setResult(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("/api/admin/esef/upload", { method: "POST", body: fd, headers: { "X-Requested-With": "InvestorIntelligence" }, credentials: "same-origin" });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Upload failed (${res.status})`);
      const r = body as UploadResult;
      setResult(
        `${r.created ? "Imported" : "Already imported"}: ${r.filing.entity_name || r.filing.lei}, year ended ${fmtDate(r.filing.period_end)} · ${fmtInt(r.facts)} numeric facts` +
          (r.skipped_dimensional ? ` (${fmtInt(r.skipped_dimensional)} breakdown facts skipped)` : "") +
          (r.linked_ticker ? ` · linked to ${r.linked_ticker}` : ""),
      );
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      mutate();
    } catch (err) {
      setOpError(err);
    } finally {
      setBusy(null);
    }
  }

  async function fetchFxo(e: React.FormEvent) {
    e.preventDefault();
    setBusy("fetch");
    setOpError(null);
    setResult(null);
    try {
      const r = await api<{ imported: number; already_present: number }>("/api/admin/esef/fetch", { method: "POST", json: { lei: lei.trim().toUpperCase() } });
      setResult(`filings.xbrl.org: ${r.imported} report(s) imported, ${r.already_present} already present.`);
      setLei("");
      mutate();
    } catch (err) {
      setOpError(err);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader title="European companies" subtitle="Fundamentals from ESEF annual reports (IFRS, inline XBRL)" />

      {isAdmin && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileUp className="size-4" /> Import an annual report
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <form onSubmit={upload} className="space-y-2">
              <Input ref={fileRef} type="file" accept=".zip,.xhtml,.html,application/zip,application/xhtml+xml" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required className="py-2" aria-label="ESEF report package" />
              <Button type="submit" className="w-full" disabled={!file || busy !== null}>
                {busy === "upload" ? <Loader2 className="animate-spin" /> : <FileUp />} Import report package
              </Button>
              <p className="text-[12px] text-muted-foreground">
                The ESEF report package (.zip) or .xhtml from the company’s investor-relations site or the national register (OAM). Read on your server; nothing is sent anywhere.
              </p>
            </form>
            <form onSubmit={fetchFxo} className="space-y-2 border-t border-border/60 pt-3">
              <Field label="Or fetch by LEI from filings.xbrl.org (optional)" htmlFor="lei">
                <Input id="lei" value={lei} onChange={(e) => setLei(e.target.value.toUpperCase())} placeholder="20-character LEI" maxLength={20} minLength={20} required autoCapitalize="characters" className="font-mono" />
              </Field>
              <Button type="submit" variant="secondary" className="w-full" disabled={busy !== null}>
                {busy === "fetch" ? <Loader2 className="animate-spin" /> : <CloudDownload />} Fetch latest reports
              </Button>
              <p className="text-[12px] text-muted-foreground">
                Free repository run by XBRL International (reports converted to xBRL-JSON). Up to 5 most recent years. Find an LEI at search.gleif.org.
              </p>
            </form>
            <ErrorNote error={opError} />
            {result && <p className="text-[13px] text-positive">{result}</p>}
          </CardContent>
        </Card>
      )}

      <ErrorNote error={error} />
      {!data && !error && <Skeleton className="h-32" />}
      {data?.length === 0 && (
        <EmptyState icon={Globe2} title="No European companies yet">
          {isAdmin ? "Import an ESEF annual report above." : "An administrator can import ESEF annual reports."}
        </EmptyState>
      )}
      <ul className="space-y-2">
        {data?.map((c) => (
          <li key={c.lei} className="rounded-2xl border border-border/60 bg-card p-3.5">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="font-semibold">
                  {c.ticker ? (
                    <Link href={`/company?t=${encodeURIComponent(c.ticker)}`} className="text-primary">
                      {c.ticker}
                    </Link>
                  ) : (
                    <Badge variant="warning">No ticker</Badge>
                  )}{" "}
                  <span className="font-normal">{c.entity_name || "Unnamed entity"}</span>
                </p>
                <p className="font-mono text-[11px] text-muted-foreground">LEI {c.lei}</p>
              </div>
              {c.exchange && <Badge variant="muted">{c.exchange}</Badge>}
            </div>
            <ul className="mt-2 divide-y divide-border/50 text-[13px]">
              {c.reports.map((r) => (
                <li key={r.id} className="flex items-center gap-2 py-1.5">
                  <span className="flex-1">
                    FY {fmtDate(r.period_end)} · {fmtInt(r.fact_count)} facts
                    <span className="block text-[11px] text-muted-foreground">
                      {r.source === "upload" ? "Uploaded" : r.source} {fmtRelative(r.imported_at)}
                    </span>
                  </span>
                  {r.viewer_url && (
                    <a href={r.viewer_url} target="_blank" rel="noreferrer" aria-label="Open report viewer" className="p-1 text-muted-foreground">
                      <ExternalLink className="size-4" />
                    </a>
                  )}
                  {isAdmin && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-8"
                      aria-label="Delete report"
                      onClick={async () => {
                        if (!confirm(`Delete the FY ${r.period_end} report and its figures?`)) return;
                        await api(`/api/admin/esef/filings/${r.id}`, { method: "DELETE" });
                        mutate();
                      }}
                    >
                      <Trash2 className="size-4 text-muted-foreground" />
                    </Button>
                  )}
                </li>
              ))}
            </ul>
            {isAdmin && !c.ticker && <LinkForm lei={c.lei} name={c.entity_name} onDone={() => mutate()} />}
          </li>
        ))}
      </ul>
      <SourceLine>
        Only the consolidated, non-breakdown numbers tagged with IFRS concepts are used for statements; company-specific tags are stored but not mapped.
        ESEF reports are annual, so there are no quarterly figures. A later report’s restated comparatives replace the earlier figures.
      </SourceLine>
    </div>
  );
}
