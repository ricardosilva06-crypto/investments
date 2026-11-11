"use client";

import * as React from "react";
import Link from "next/link";
import useSWR from "swr";
import { ExternalLink, FileText, Loader2, RefreshCw, Sparkles, Trash2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorNote, PageHeader, SourceLine } from "@/components/page";
import { api } from "@/lib/api";
import { fmtRelative } from "@/lib/format";
import type { DocItem } from "@/lib/types";

const STATUS: Record<DocItem["status"], { label: string; variant: "positive" | "muted" | "warning" | "negative" | "default" }> = {
  ready: { label: "Semantic + keyword", variant: "positive" },
  keyword_only: { label: "Keyword search", variant: "muted" },
  indexing: { label: "Indexing…", variant: "default" },
  ocr: { label: "Reading scans (OCR)…", variant: "default" },
  extracted: { label: "Processing…", variant: "default" },
  error: { label: "Error", variant: "negative" },
};

export default function DocumentsPage() {
  const { data, error, mutate } = useSWR<DocItem[]>("/api/documents", {
    refreshInterval: (d) => (d?.some((x) => x.status === "indexing" || x.status === "extracted" || x.status === "ocr") ? 2000 : 0),
  });
  const { data: ocr } = useSWR<{ available: boolean; reason: string; languages: string[]; default: string; max_pages: number }>("/api/documents/ocr-status");
  const [ocrLang, setOcrLang] = React.useState("");
  const [file, setFile] = React.useState<File | null>(null);
  const [title, setTitle] = React.useState("");
  const [ticker, setTicker] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [upError, setUpError] = React.useState<unknown>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);

  async function upload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setUpError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("title", title);
      fd.append("ticker", ticker);
      if (ocrLang) fd.append("ocr_language", ocrLang);
      const res = await fetch("/api/documents", { method: "POST", body: fd, headers: { "X-Requested-With": "InvestorIntelligence" }, credentials: "same-origin" });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Upload failed (${res.status})`);
      setFile(null);
      setTitle("");
      setTicker("");
      if (fileRef.current) fileRef.current.value = "";
      mutate();
    } catch (err) {
      setUpError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Documents" subtitle="Private PDFs for the AI analyst: annual reports, earnings releases…" />

      <Card>
        <CardHeader>
          <CardTitle>Upload PDF</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={upload} className="space-y-3">
            <Input ref={fileRef} type="file" accept="application/pdf,.pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required className="py-2" aria-label="PDF file" />
            <div className="grid grid-cols-[1fr_7rem] gap-2">
              <Field label="Title (optional)" htmlFor="dt">
                <Input id="dt" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={255} placeholder={file?.name.replace(/\.pdf$/i, "") ?? "e.g. Annual report 2024"} />
              </Field>
              <Field label="Ticker" htmlFor="dk">
                <Input id="dk" value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} maxLength={20} autoCapitalize="characters" autoCorrect="off" placeholder="opt." />
              </Field>
            </div>
            {ocr?.available && (
              <Field label="Language of scanned pages (OCR)" htmlFor="ol">
                <NativeSelect id="ol" value={ocrLang} onChange={(e) => setOcrLang(e.target.value)}>
                  <option value="">Default ({ocr.default})</option>
                  {ocr.languages.map((l) => (
                    <option key={l} value={l}>
                      {l}
                    </option>
                  ))}
                  {ocr.languages.length > 1 && <option value={ocr.languages.join("+")}>All installed ({ocr.languages.join("+")})</option>}
                </NativeSelect>
              </Field>
            )}
            <ErrorNote error={upError} />
            <Button type="submit" className="w-full" disabled={!file || busy}>
              {busy ? <Loader2 className="animate-spin" /> : <Upload />} {busy ? "Extracting text…" : "Upload"}
            </Button>
          </form>
          <SourceLine>
            Text is extracted on your server (PyMuPDF). Files stay on your machine and are visible only to you.{" "}
            {ocr?.available
              ? `Scanned pages are read with local OCR (Tesseract; up to ${ocr.max_pages} pages, about 1–3 s per page); recognised numbers can contain errors.`
              : ocr
                ? `Scanned PDFs need the free Tesseract OCR engine on the server (${ocr.reason}) See README.`
                : ""}
          </SourceLine>
        </CardContent>
      </Card>

      <ErrorNote error={error} />
      {!data && !error && <Skeleton className="h-32" />}
      {data?.length === 0 && (
        <EmptyState icon={FileText} title="No documents yet">
          Upload an annual report and ask the AI analyst about it.
        </EmptyState>
      )}
      <ul className="space-y-2">
        {data?.map((d) => (
          <li key={d.id} className="rounded-2xl border border-border/60 bg-card p-3.5">
            <div className="flex items-start gap-3">
              <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent text-accent-foreground">
                <FileText className="size-5" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold">{d.title}</p>
                <p className="text-[12px] text-muted-foreground">
                  {d.pages} pages · {(d.size_bytes / 1024 / 1024).toFixed(1)} MB{d.ticker ? ` · ${d.ticker}` : ""} · {fmtRelative(d.created_at)}
                </p>
                {d.ocr_pages > 0 && (
                  <p className="text-[12px] text-warning">
                    {d.ocr_pages} page{d.ocr_pages === 1 ? "" : "s"} read with OCR ({d.ocr_language}): check important numbers against the PDF.
                  </p>
                )}
                <div className="mt-1 flex items-center gap-1.5">
                  <Badge variant={STATUS[d.status].variant}>{STATUS[d.status].label}</Badge>
                </div>
                {d.message && <p className="mt-1 text-[12px] text-muted-foreground">{d.message}</p>}
              </div>
            </div>
            <div className="mt-3 grid grid-cols-[1fr_auto_auto_auto] gap-2">
              <Button size="sm" asChild>
                <Link href={`/analyst?task=document&d=${d.id}${d.ticker ? `&t=${d.ticker}` : ""}`}>
                  <Sparkles /> Ask AI
                </Link>
              </Button>
              <Button size="sm" variant="secondary" asChild aria-label="Open PDF">
                <a href={`/api/documents/${d.id}/file`} target="_blank" rel="noreferrer">
                  <ExternalLink />
                </a>
              </Button>
              <Button
                size="sm"
                variant="secondary"
                aria-label="Rebuild search index"
                onClick={async () => {
                  await api(`/api/documents/${d.id}/reindex`, { method: "POST" });
                  setTimeout(() => mutate(), 300);
                }}
              >
                <RefreshCw />
              </Button>
              <Button
                size="sm"
                variant="destructive"
                aria-label="Delete document"
                onClick={async () => {
                  if (!confirm(`Delete “${d.title}”?`)) return;
                  await api(`/api/documents/${d.id}`, { method: "DELETE" });
                  mutate();
                }}
              >
                <Trash2 />
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
