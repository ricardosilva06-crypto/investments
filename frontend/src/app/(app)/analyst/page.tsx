"use client";

import useSWR from "swr";
import { CheckCircle2, Cpu, RefreshCw, ShieldCheck, Sparkles, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/page";
import type { SystemStatus } from "@/lib/types";

export default function AnalystPage() {
  const { data, isValidating, mutate } = useSWR<SystemStatus>("/api/system/status");
  const ai = data?.ai;

  return (
    <div>
      <PageHeader title="AI Analyst" subtitle="Runs locally with Ollama. No paid AI API and no API key." />

      <Card>
        <CardHeader>
          <CardTitle>Local model status</CardTitle>
          <Button variant="ghost" size="sm" onClick={() => mutate()} disabled={isValidating} aria-label="Check again">
            <RefreshCw className={isValidating ? "animate-spin" : ""} />
          </Button>
        </CardHeader>
        <CardContent>
          {!ai ? (
            <Skeleton className="h-14" />
          ) : ai.available ? (
            <div className="space-y-2">
              <p className="flex items-center gap-2 font-semibold text-positive">
                <CheckCircle2 className="size-5" /> Ollama is running
              </p>
              {ai.models.length ? (
                <ul className="flex flex-wrap gap-1.5">
                  {ai.models.map((m) => (
                    <li key={m} className="rounded-lg bg-elevated px-2 py-1 font-mono text-[12px]">
                      {m}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[13px] text-muted-foreground">No models installed yet. Run e.g. `ollama pull llama3.1:8b` on the server.</p>
              )}
            </div>
          ) : (
            <div className="space-y-1">
              <p className="flex items-center gap-2 font-semibold">
                <XCircle className="size-5 text-muted-foreground" /> AI is unavailable
              </p>
              <p className="text-[13px] text-muted-foreground">{ai.message} Everything else in the app keeps working without it.</p>
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>What is coming in Phase 3</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-[14px]">
          <div className="flex gap-3">
            <Sparkles className="mt-0.5 size-4 shrink-0 text-primary" />
            <p>Chat with a local model about companies, earnings and your portfolio, with follow-up questions and saved theses.</p>
          </div>
          <div className="flex gap-3">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-primary" />
            <p>Answers grounded in this app’s database and your uploaded PDFs (retrieval-augmented), with verified data, calculations, assumptions and opinions clearly labelled.</p>
          </div>
          <div className="flex gap-3">
            <Cpu className="mt-0.5 size-4 shrink-0 text-primary" />
            <p>Choose any Ollama-compatible open model. Inference stays on your own hardware.</p>
          </div>
          <p className="text-[12px] text-muted-foreground">
            The chat is not enabled yet because answers without verified data and retrieval could invent financial figures.
          </p>
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Set up Ollama on the server</CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="list-decimal space-y-1.5 pl-5 text-[14px]">
            <li>Install Ollama (free, open source) from ollama.com on the computer running this app.</li>
            <li>
              Pull a model, for example <code className="rounded bg-elevated px-1 font-mono text-[12px]">ollama pull llama3.1:8b</code> or{" "}
              <code className="rounded bg-elevated px-1 font-mono text-[12px]">ollama pull qwen2.5:7b</code>.
            </li>
            <li>Keep Ollama running; it listens on {ai?.url ?? "http://127.0.0.1:11434"}.</li>
            <li>Tap refresh above. The status should turn green.</li>
          </ol>
          <p className="mt-2 text-[12px] text-muted-foreground">8B-parameter models need roughly 8 GB of RAM; larger models need more.</p>
        </CardContent>
      </Card>
    </div>
  );
}
