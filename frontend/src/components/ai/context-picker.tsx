"use client";

import * as React from "react";
import useSWR from "swr";
import { Building2, Check, FileText, Search, Upload } from "lucide-react";
import Link from "next/link";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import type { DocItem, SearchHit } from "@/lib/types";
import { cn } from "@/lib/utils";

export function CompanyPicker({ open, onOpenChange, selected, onToggle }: { open: boolean; onOpenChange: (o: boolean) => void; selected: string[]; onToggle: (t: string) => void }) {
  const [q, setQ] = React.useState("");
  const [dq, setDq] = React.useState("");
  React.useEffect(() => {
    const t = setTimeout(() => setDq(q.trim()), 200);
    return () => clearTimeout(t);
  }, [q]);
  const { data } = useSWR<SearchHit[]>(open && dq ? `/api/search?q=${encodeURIComponent(dq)}` : null);
  const hits = (data ?? []).filter((h) => h.type === "security");
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent title="Companies" description="Up to 3. Their SEC data and stored prices become sources.">
        <div className="space-y-2 px-4 pb-6">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Ticker or company"
              autoCorrect="off"
              className="h-11 w-full rounded-xl border border-input bg-elevated pr-3 pl-10 outline-none focus-visible:border-primary"
            />
          </div>
          {selected.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {selected.map((t) => (
                <button key={t} onClick={() => onToggle(t)} className="rounded-full bg-primary px-2.5 py-1 text-[12px] font-semibold text-primary-foreground">
                  {t} ×
                </button>
              ))}
            </div>
          )}
          <ul className="divide-y divide-border/60 overflow-hidden rounded-2xl border border-border/60">
            {hits.map((h) => {
              const on = selected.includes(h.title);
              return (
                <li key={h.title}>
                  <button
                    disabled={!on && selected.length >= 3}
                    onClick={() => onToggle(h.title)}
                    className="flex w-full items-center gap-3 px-3.5 py-3 text-left disabled:opacity-40"
                  >
                    <Building2 className="size-4 text-muted-foreground" />
                    <span className="min-w-0 flex-1">
                      <span className="block font-semibold">{h.title}</span>
                      <span className="block truncate text-[12px] text-muted-foreground">{h.subtitle}</span>
                    </span>
                    <span className={cn("grid size-6 place-items-center rounded-full border", on ? "border-primary bg-primary text-primary-foreground" : "border-border")}>
                      {on && <Check className="size-3.5" />}
                    </span>
                  </button>
                </li>
              );
            })}
            {dq && data && hits.length === 0 && <li className="p-3 text-[13px] text-muted-foreground">No matching company.</li>}
            {!dq && <li className="p-3 text-[13px] text-muted-foreground">Search the SEC company list.</li>}
          </ul>
        </div>
      </SheetContent>
    </Sheet>
  );
}

export function DocumentPicker({ open, onOpenChange, selected, onToggle }: { open: boolean; onOpenChange: (o: boolean) => void; selected: number[]; onToggle: (id: number) => void }) {
  const { data } = useSWR<DocItem[]>(open ? "/api/documents" : null);
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent title="Documents" description="Relevant passages from these PDFs become sources.">
        <div className="space-y-2 px-4 pb-6">
          <Link href="/documents" className="flex items-center justify-center gap-2 rounded-xl bg-elevated py-3 text-[14px] font-medium">
            <Upload className="size-4" /> Upload a PDF
          </Link>
          <ul className="divide-y divide-border/60 overflow-hidden rounded-2xl border border-border/60">
            {data?.map((d) => {
              const on = selected.includes(d.id);
              return (
                <li key={d.id}>
                  <button onClick={() => onToggle(d.id)} className="flex w-full items-center gap-3 px-3.5 py-3 text-left">
                    <FileText className="size-4 text-muted-foreground" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{d.title}</span>
                      <span className="text-[12px] text-muted-foreground">
                        {d.pages} pages{d.ticker ? ` · ${d.ticker}` : ""} · {d.status === "ready" ? "semantic + keyword search" : "keyword search"}
                      </span>
                    </span>
                    <span className={cn("grid size-6 place-items-center rounded-full border", on ? "border-primary bg-primary text-primary-foreground" : "border-border")}>
                      {on && <Check className="size-3.5" />}
                    </span>
                  </button>
                </li>
              );
            })}
            {data?.length === 0 && <li className="p-3 text-[13px] text-muted-foreground">No documents uploaded yet.</li>}
          </ul>
        </div>
      </SheetContent>
    </Sheet>
  );
}
