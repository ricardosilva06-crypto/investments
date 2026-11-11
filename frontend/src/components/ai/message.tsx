"use client";

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, BookmarkPlus, Check, CheckCircle2, Copy, ExternalLink, FileText, Loader2 } from "lucide-react";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import type { AISource, ChatMsg, Verification } from "@/lib/types";
import { cn } from "@/lib/utils";
import { AnswerMarkdown } from "./markdown";

const KIND_LABEL: Record<string, string> = {
  company: "SEC profile",
  financials: "SEC financials",
  calc: "Calculated by app",
  price: "End-of-day price",
  document: "Your document",
  note: "Your note (opinion)",
  portfolio: "Your portfolio",
};

export function SourcesSheet({ sources, focus, onClose }: { sources: AISource[]; focus: string | null; onClose: () => void }) {
  const ref = React.useRef<HTMLLIElement | null>(null);
  React.useEffect(() => {
    if (focus) setTimeout(() => ref.current?.scrollIntoView({ block: "center" }), 250);
  }, [focus]);
  return (
    <Sheet open={focus !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent title="Sources" description="Everything the model was given for this answer">
        <ul className="space-y-2 px-4 pb-6">
          {sources.map((s) => (
            <li
              key={s.id}
              ref={s.id === focus ? ref : undefined}
              className={cn("rounded-2xl border border-border/60 p-3", s.id === focus && "border-primary bg-accent/40")}
            >
              <div className="flex items-center gap-2">
                <span className="rounded-md bg-accent px-1.5 py-0.5 font-mono text-[11px] font-bold text-accent-foreground">{s.id}</span>
                <span className="min-w-0 flex-1 truncate text-[14px] font-medium">{s.label}</span>
              </div>
              <p className="mt-1 text-[12px] text-muted-foreground">{KIND_LABEL[s.kind] ?? s.kind}</p>
              {s.detail && <p className="mt-1 line-clamp-4 text-[12px] text-muted-foreground italic">“{s.detail}…”</p>}
              {s.url &&
                (s.url.startsWith("/api/") ? (
                  <a href={s.url} target="_blank" rel="noreferrer" className="mt-1.5 inline-flex items-center gap-1 text-[13px] font-medium text-primary">
                    Open page <ExternalLink className="size-3" />
                  </a>
                ) : (
                  <Link href={s.url} className="mt-1.5 inline-flex items-center gap-1 text-[13px] font-medium text-primary">
                    Open <ExternalLink className="size-3" />
                  </Link>
                ))}
            </li>
          ))}
          {sources.length === 0 && <li className="text-[13px] text-muted-foreground">No sources were provided for this answer.</li>}
        </ul>
      </SheetContent>
    </Sheet>
  );
}

export function VerificationBadge({ v, streaming }: { v: Verification; streaming?: boolean }) {
  const [open, setOpen] = React.useState(false);
  if (streaming) return null;
  if (v.checked === undefined) return null;
  const bad = v.unmatched_verified ?? [];
  const other = v.unmatched_other ?? [];
  const ok = bad.length === 0;
  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen(!open)}
        className={cn(
          "flex items-center gap-1.5 rounded-lg px-2 py-1 text-[12px] font-medium",
          ok ? "bg-positive/10 text-positive" : "bg-warning/15 text-warning",
        )}
      >
        {ok ? <CheckCircle2 className="size-3.5" /> : <AlertTriangle className="size-3.5" />}
        {ok
          ? `${v.checked} numbers checked · verified-data figures match sources`
          : `${bad.length} figure${bad.length > 1 ? "s" : ""} in “Verified data” not found in sources`}
      </button>
      {open && (
        <div className="mt-1.5 space-y-1 rounded-xl bg-elevated p-2.5 text-[12px] text-muted-foreground">
          <p>Every number in the answer was compared with the numbers in the sources given to the model.</p>
          {bad.length > 0 && (
            <p className="text-warning">
              Not found (treat as unverified): <span className="font-mono">{bad.join(", ")}</span>
            </p>
          )}
          {other.length > 0 && (
            <p>
              New numbers in calculations/assumptions/opinion (expected if computed or assumed): <span className="font-mono">{other.join(", ")}</span>
            </p>
          )}
          {v.has_structure === false && <p className="text-warning">The model did not follow the required section structure.</p>}
        </div>
      )}
    </div>
  );
}

export function AssistantMessage({ m, streaming }: { m: ChatMsg; streaming?: boolean }) {
  const [focus, setFocus] = React.useState<string | null>(null);
  const [saved, setSaved] = React.useState<number | null>(null);
  const [copied, setCopied] = React.useState(false);
  const [busy, setBusy] = React.useState(false);

  async function save() {
    setBusy(true);
    try {
      const r = await api<{ note_id: number }>(`/api/ai/messages/${m.id}/save-note`, { method: "POST", json: {} });
      setSaved(r.note_id);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-2xl rounded-tl-md border border-border/60 bg-card px-3.5 py-3">
      {m.content ? (
        <AnswerMarkdown text={m.content} onCite={setFocus} />
      ) : (
        <p className="flex items-center gap-2 text-[14px] text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Thinking locally… (first answer may take a while while the model loads)
        </p>
      )}
      {streaming && m.content && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-primary align-middle" />}
      {m.status === "error" && <p className="mt-2 text-[13px] text-negative">The answer could not be completed.</p>}
      {m.status === "partial" && <p className="mt-2 text-[13px] text-warning">The answer was interrupted and may be incomplete.</p>}
      <VerificationBadge v={m.verification} streaming={streaming} />
      {!streaming && m.id > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-border/50 pt-2">
          <button onClick={() => setFocus(m.sources[0]?.id ?? "")} className="flex items-center gap-1 rounded-lg bg-elevated px-2 py-1 text-[12px] font-medium">
            <FileText className="size-3.5" /> {m.sources.length} sources
          </button>
          {saved ? (
            <Link href={`/notes?id=${saved}`} className="flex items-center gap-1 rounded-lg bg-positive/10 px-2 py-1 text-[12px] font-medium text-positive">
              <Check className="size-3.5" /> Saved to notes
            </Link>
          ) : (
            <button onClick={save} disabled={busy} className="flex items-center gap-1 rounded-lg bg-elevated px-2 py-1 text-[12px] font-medium">
              <BookmarkPlus className="size-3.5" /> Save as thesis
            </button>
          )}
          <button
            onClick={() => {
              navigator.clipboard?.writeText(m.content);
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            }}
            className="flex items-center gap-1 rounded-lg bg-elevated px-2 py-1 text-[12px] font-medium"
          >
            {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />} Copy
          </button>
          <Badge variant="muted" className="ml-auto font-mono">
            {m.model}
          </Badge>
        </div>
      )}
      <p className="mt-1.5 text-[11px] text-muted-foreground">AI output can be wrong. Not investment advice.</p>
      <SourcesSheet sources={m.sources} focus={focus} onClose={() => setFocus(null)} />
    </div>
  );
}
