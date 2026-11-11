"use client";

import * as React from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { ArrowUp, Building2, FileText, History, Plus, RefreshCw, Settings2, Sparkles, Square, Trash2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, NativeSelect } from "@/components/ui/input";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorNote } from "@/components/page";
import { AssistantMessage } from "@/components/ai/message";
import { CompanyPicker, DocumentPicker } from "@/components/ai/context-picker";
import { api } from "@/lib/api";
import { postSSE } from "@/lib/sse";
import { fmtRelative } from "@/lib/format";
import type { AISource, AIStatus, ChatMsg, ConversationDetail, ConversationSummary, DocItem, Verification } from "@/lib/types";
import { cn } from "@/lib/utils";

const TASK_ORDER = ["ask", "company_analysis", "bull_bear", "earnings", "financials", "valuation", "compare", "thesis", "portfolio", "document"];
const TASK_HINT: Record<string, string> = {
  ask: "Ask anything about the selected companies, documents or your portfolio",
  company_analysis: "Research report from SEC data (and documents)",
  bull_bear: "Balanced bull and bear case",
  earnings: "Latest quarters: what changed",
  financials: "Income, balance sheet and cash-flow quality",
  valuation: "Which multiples are computable and what they mean",
  compare: "Side-by-side comparison (2–3 companies)",
  thesis: "Draft an investment thesis to save in Notes",
  portfolio: "Concentration, results and questions about your portfolio",
  document: "Summarise and analyse the selected PDF",
};

function SetupCard({ status, onRetry }: { status: AIStatus; onRetry: () => void }) {
  return (
    <Card className="mt-2">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <XCircle className="size-4" /> AI is unavailable
        </CardTitle>
        <Button variant="ghost" size="sm" onClick={onRetry} aria-label="Check again">
          <RefreshCw />
        </Button>
      </CardHeader>
      <CardContent className="space-y-2 text-[14px]">
        <p className="text-muted-foreground">{status.message} Everything else in the app keeps working.</p>
        <ol className="list-decimal space-y-1 pl-5">
          <li>Install Ollama (free, open source) on the computer running this app.</li>
          <li>
            Pull a chat model, e.g. <code className="rounded bg-elevated px-1 font-mono text-[12px]">ollama pull llama3.1:8b</code> or{" "}
            <code className="rounded bg-elevated px-1 font-mono text-[12px]">ollama pull qwen2.5:7b</code>.
          </li>
          <li>
            Optional, for better PDF search: <code className="rounded bg-elevated px-1 font-mono text-[12px]">ollama pull nomic-embed-text</code>.
          </li>
          <li>Keep Ollama running ({status.url}) and tap refresh.</li>
        </ol>
        <p className="text-[12px] text-muted-foreground">7–8B models need about 8 GB of RAM. Inference runs on your hardware; nothing is sent to a cloud AI.</p>
      </CardContent>
    </Card>
  );
}

export default function AnalystPage() {
  const router = useRouter();
  const params = useSearchParams();
  const convId = Number(params.get("c")) || null;
  const { data: status, mutate: mutateStatus, isLoading: statusLoading } = useSWR<AIStatus>("/api/ai/status", { revalidateOnFocus: false });
  const { data: convs, mutate: mutateConvs } = useSWR<ConversationSummary[]>("/api/ai/conversations");
  const { data: conv } = useSWR<ConversationDetail>(convId ? `/api/ai/conversations/${convId}` : null, { revalidateOnFocus: false });
  const { data: docs } = useSWR<DocItem[]>("/api/documents");

  const [messages, setMessages] = React.useState<ChatMsg[]>([]);
  const [loadedConv, setLoadedConv] = React.useState<number | null>(null);
  const [task, setTask] = React.useState(params.get("task") ?? "ask");
  const [tickers, setTickers] = React.useState<string[]>(params.get("t") ? [params.get("t")!.toUpperCase()] : []);
  const [docIds, setDocIds] = React.useState<number[]>(params.get("d") ? [Number(params.get("d"))] : []);
  const [input, setInput] = React.useState("");
  const [streaming, setStreaming] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);
  const [warnings, setWarnings] = React.useState<string[]>([]);
  const [sheet, setSheet] = React.useState<null | "history" | "settings" | "company" | "docs">(null);
  const abortRef = React.useRef<AbortController | null>(null);
  const bottomRef = React.useRef<HTMLDivElement>(null);

  // Load a stored conversation once (render-time sync, no effect).
  if (conv && conv.id !== loadedConv) {
    setLoadedConv(conv.id);
    setMessages(conv.messages);
    const lastUser = [...conv.messages].reverse().find((m) => m.role === "user");
    if (lastUser) {
      setTickers(lastUser.tickers);
      setDocIds(lastUser.document_ids);
    }
  }
  if (!convId && loadedConv !== null && !streaming) {
    setLoadedConv(null);
    setMessages([]);
  }

  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, streaming]);

  const docTitle = (id: number) => docs?.find((d) => d.id === id)?.title ?? `Document ${id}`;

  async function send() {
    if (streaming) return;
    setError(null);
    setWarnings([]);
    const question = input.trim();
    const userMsg: ChatMsg = {
      id: -Date.now(), role: "user", content: question || (status?.tasks[task] ?? task), task, tickers, document_ids: docIds,
      model: "", sources: [], verification: {}, status: "ok", created_at: new Date().toISOString(),
    };
    const draft: ChatMsg = { ...userMsg, id: 0, role: "assistant", content: "" };
    setMessages((m) => [...m, userMsg, draft]);
    setInput("");
    setStreaming(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    let newConv: number | null = convId;
    let sources: AISource[] = [];
    let model = "";
    const update = (fn: (m: ChatMsg) => ChatMsg) => setMessages((ms) => [...ms.slice(0, -1), fn(ms[ms.length - 1])]);
    try {
      await postSSE(
        "/api/ai/chat",
        { conversation_id: convId, message: question, task, tickers, document_ids: docIds },
        (event, data) => {
          const d = data as Record<string, unknown>;
          if (event === "meta") {
            newConv = d.conversation_id as number;
            sources = d.sources as AISource[];
            model = d.model as string;
            setWarnings((d.warnings as string[]) ?? []);
            update((m) => ({ ...m, sources, model }));
          } else if (event === "token") {
            update((m) => ({ ...m, content: m.content + (d.t as string) }));
          } else if (event === "error") {
            setError(new Error(d.message as string));
          } else if (event === "done") {
            update((m) => ({ ...m, id: d.message_id as number, verification: d.verification as Verification, status: d.status as string }));
          }
        },
        ctrl.signal,
      );
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setError(e);
        setMessages((ms) => (ms[ms.length - 1]?.content ? ms : ms.slice(0, -2)));
        if (!input) setInput(question);
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
      mutateConvs();
      if (newConv && newConv !== convId) {
        setLoadedConv(newConv);
        router.replace(`/analyst?c=${newConv}`, { scroll: false });
      }
    }
  }

  function newChat() {
    setMessages([]);
    setLoadedConv(null);
    setTask("ask");
    setError(null);
    router.replace("/analyst", { scroll: false });
  }

  const available = status?.available;
  const placeholder = task === "ask" ? "Ask a question…" : "Optional focus or question…";
  const canSend =
    available &&
    !streaming &&
    (input.trim() || task !== "ask") &&
    !(["company_analysis", "bull_bear", "earnings", "financials", "valuation", "thesis"].includes(task) && tickers.length === 0) &&
    !(task === "compare" && tickers.length < 2) &&
    !(task === "document" && docIds.length === 0);

  return (
    <div className="pb-48">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="min-w-0">
          <h1 className="text-[28px] font-bold tracking-tight">AI Analyst</h1>
          <p className="truncate text-[12px] text-muted-foreground">
            {statusLoading ? "Checking local model…" : available ? `Local · ${status?.chat_model}` : "Local AI offline"}
          </p>
        </div>
        <div className="flex gap-1">
          <Button variant="secondary" size="icon" onClick={() => setSheet("history")} aria-label="Conversation history">
            <History className="size-5" />
          </Button>
          <Button variant="secondary" size="icon" onClick={() => setSheet("settings")} aria-label="Model settings">
            <Settings2 className="size-5" />
          </Button>
          <Button variant="secondary" size="icon" onClick={newChat} aria-label="New conversation">
            <Plus className="size-5" />
          </Button>
        </div>
      </div>

      {status && !available && <SetupCard status={status} onRetry={() => mutateStatus()} />}

      {messages.length === 0 && available && (
        <div className="mt-2 space-y-3">
          <div className="rounded-2xl bg-gradient-to-br from-primary/15 to-transparent p-4 ring-1 ring-primary/20">
            <p className="flex items-center gap-2 font-semibold">
              <Sparkles className="size-4 text-primary" /> Grounded, local analysis
            </p>
            <p className="mt-1 text-[13px] text-muted-foreground">
              Answers use only data from this app (SEC filings, stored prices, your portfolio) and your PDFs, with numbered sources. Each answer
              separates verified data, calculations, assumptions and opinion, and every number is checked against the sources.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {TASK_ORDER.filter((t) => t !== "ask").map((t) => (
              <button
                key={t}
                onClick={() => {
                  setTask(t);
                  if (["company_analysis", "bull_bear", "earnings", "financials", "valuation", "thesis", "compare"].includes(t) && tickers.length === 0) setSheet("company");
                  if (t === "document" && docIds.length === 0) setSheet("docs");
                }}
                className={cn("rounded-xl border border-border/60 bg-card p-3 text-left active:scale-[0.98]", task === t && "border-primary")}
              >
                <p className="text-[14px] font-semibold">{status?.tasks[t]}</p>
                <p className="mt-0.5 text-[12px] text-muted-foreground">{TASK_HINT[t]}</p>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="mt-2 space-y-3">
        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={m.id || i} className="ml-10 rounded-2xl rounded-tr-md bg-primary/15 px-3.5 py-2.5 text-[15px]">
              {m.task !== "ask" && <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">{status?.tasks[m.task] ?? m.task}</p>}
              <p className="whitespace-pre-wrap">{m.content}</p>
              {(m.tickers.length > 0 || m.document_ids.length > 0) && (
                <p className="mt-1 text-[11px] text-muted-foreground">
                  {[...m.tickers, ...m.document_ids.map(docTitle)].join(" · ")}
                </p>
              )}
            </div>
          ) : (
            <AssistantMessage key={m.id || `draft-${i}`} m={m} streaming={streaming && i === messages.length - 1} />
          ),
        )}
        {warnings.length > 0 && (
          <div className="rounded-xl bg-warning/10 px-3 py-2 text-[12px] text-warning">{warnings.join(" ")}</div>
        )}
        <ErrorNote error={error} />
        <div ref={bottomRef} />
      </div>

      {/* Composer, fixed above the bottom navigation (portalled: the page transition uses a transform) */}
      <BodyPortal>
      <div className="fixed inset-x-0 bottom-[calc(58px+env(safe-area-inset-bottom))] z-30 border-t border-border/60 bg-nav backdrop-blur-xl">
        <div className="mx-auto max-w-xl px-safe py-2">
          <div className="no-scrollbar -mx-4 flex gap-1.5 overflow-x-auto px-4 pb-2">
            {TASK_ORDER.map((t) => (
              <button
                key={t}
                onClick={() => setTask(t)}
                className={cn(
                  "shrink-0 rounded-full border border-border px-2.5 py-1 text-[12px] font-medium",
                  task === t ? "border-primary bg-primary text-primary-foreground" : "bg-card text-muted-foreground",
                )}
              >
                {status?.tasks[t] ?? t}
              </button>
            ))}
          </div>
          <div className="mb-2 flex flex-wrap items-center gap-1.5">
            <button onClick={() => setSheet("company")} className="flex items-center gap-1 rounded-lg bg-elevated px-2 py-1 text-[12px] font-medium">
              <Building2 className="size-3.5" /> {tickers.length ? tickers.join(", ") : "Company"}
            </button>
            <button onClick={() => setSheet("docs")} className="flex max-w-[55%] items-center gap-1 rounded-lg bg-elevated px-2 py-1 text-[12px] font-medium">
              <FileText className="size-3.5 shrink-0" />
              <span className="truncate">{docIds.length ? docIds.map(docTitle).join(", ") : "Documents"}</span>
            </button>
            {(tickers.length > 0 || docIds.length > 0) && (
              <button
                onClick={() => {
                  setTickers([]);
                  setDocIds([]);
                }}
                className="rounded-lg px-1.5 py-1 text-[12px] text-muted-foreground"
                aria-label="Clear context"
              >
                <Trash2 className="size-3.5" />
              </button>
            )}
          </div>
          <form
            className="flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (canSend) send();
            }}
          >
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && window.matchMedia("(pointer: fine)").matches) {
                  e.preventDefault();
                  if (canSend) send();
                }
              }}
              rows={1}
              maxLength={4000}
              placeholder={available ? placeholder : "AI unavailable"}
              disabled={!available}
              className="max-h-32 min-h-11 flex-1 resize-none rounded-2xl border border-input bg-elevated px-3.5 py-2.5 outline-none focus-visible:border-primary disabled:opacity-50"
              aria-label="Message"
            />
            {streaming ? (
              <Button type="button" size="icon" className="size-11 shrink-0 rounded-full" onClick={() => abortRef.current?.abort()} aria-label="Stop">
                <Square className="size-4" />
              </Button>
            ) : (
              <Button type="submit" size="icon" className="size-11 shrink-0 rounded-full" disabled={!canSend} aria-label="Send">
                <ArrowUp className="size-5" />
              </Button>
            )}
          </form>
        </div>
      </div>
      </BodyPortal>

      <CompanyPicker
        open={sheet === "company"}
        onOpenChange={(o) => setSheet(o ? "company" : null)}
        selected={tickers}
        onToggle={(t) => setTickers((cur) => (cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t].slice(0, 3)))}
      />
      <DocumentPicker
        open={sheet === "docs"}
        onOpenChange={(o) => setSheet(o ? "docs" : null)}
        selected={docIds}
        onToggle={(id) => setDocIds((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id].slice(0, 10)))}
      />

      <Sheet open={sheet === "history"} onOpenChange={(o) => setSheet(o ? "history" : null)}>
        <SheetContent title="Conversations" description="Private to you">
          <ul className="space-y-1.5 px-4 pb-6">
            {convs?.map((c) => (
              <li key={c.id} className="flex items-center gap-2">
                <Link
                  href={`/analyst?c=${c.id}`}
                  onClick={() => setSheet(null)}
                  className={cn("min-w-0 flex-1 rounded-xl bg-elevated px-3 py-2.5", c.id === convId && "ring-1 ring-primary")}
                >
                  <span className="block truncate text-[14px] font-medium">{c.title}</span>
                  <span className="text-[11px] text-muted-foreground">{fmtRelative(c.updated_at)}</span>
                </Link>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Delete conversation"
                  onClick={async () => {
                    if (!confirm(`Delete “${c.title}”?`)) return;
                    await api(`/api/ai/conversations/${c.id}`, { method: "DELETE" });
                    mutateConvs();
                    if (c.id === convId) newChat();
                  }}
                >
                  <Trash2 className="text-muted-foreground" />
                </Button>
              </li>
            ))}
            {!convs && <Skeleton className="h-20" />}
            {convs?.length === 0 && <li className="text-[13px] text-muted-foreground">No conversations yet.</li>}
          </ul>
        </SheetContent>
      </Sheet>

      <Sheet open={sheet === "settings"} onOpenChange={(o) => setSheet(o ? "settings" : null)}>
        <SheetContent title="Local model" description={status?.url}>
          {status && <ModelSettings status={status} onSaved={(s) => mutateStatus(s, false)} />}
        </SheetContent>
      </Sheet>
    </div>
  );
}

function subscribeNoop() {
  return () => {};
}

function BodyPortal({ children }: { children: React.ReactNode }) {
  const mounted = React.useSyncExternalStore(subscribeNoop, () => true, () => false);
  return mounted ? createPortal(children, document.body) : null;
}

function ModelSettings({ status, onSaved }: { status: AIStatus; onSaved: (s: AIStatus) => void }) {
  const [chat, setChat] = React.useState(status.chosen_chat_model);
  const [embed, setEmbed] = React.useState(status.chosen_embed_model);
  const [temp, setTemp] = React.useState(status.temperature);
  const [error, setError] = React.useState<unknown>(null);
  const chatModels = status.models.filter((m) => !m.embedding);
  const embedModels = status.models.filter((m) => m.embedding);
  return (
    <form
      className="space-y-3 px-4 pb-6"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          onSaved(await api<AIStatus>("/api/ai/settings", { method: "PUT", json: { chat_model: chat, embed_model: embed, temperature: temp } }));
        } catch (err) {
          setError(err);
        }
      }}
    >
      {!status.available && <p className="text-[13px] text-muted-foreground">{status.message}</p>}
      <Field label="Chat model" htmlFor="cm">
        <NativeSelect id="cm" value={chat} onChange={(e) => setChat(e.target.value)}>
          <option value="">Automatic ({status.chat_model ?? "none installed"})</option>
          {chatModels.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name} {m.parameter_size && `· ${m.parameter_size}`} {m.quantization && `· ${m.quantization}`}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field label="Embedding model (PDF semantic search)" htmlFor="em">
        <NativeSelect id="em" value={embed} onChange={(e) => setEmbed(e.target.value)}>
          <option value="">Automatic ({status.embed_model ?? "none: keyword search only"})</option>
          {embedModels.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field label={`Creativity (temperature): ${Number(temp).toFixed(1)}`} htmlFor="tp">
        <input id="tp" type="range" min="0" max="1" step="0.1" value={temp} onChange={(e) => setTemp(e.target.value)} className="w-full accent-[var(--primary)]" />
      </Field>
      <p className="text-[12px] text-muted-foreground">
        Lower is more factual. Context window requested from the model: {status.num_ctx.toLocaleString()} tokens (server setting II_OLLAMA_NUM_CTX).
      </p>
      <ErrorNote error={error} />
      <Button type="submit" className="w-full">
        Save
      </Button>
    </form>
  );
}
