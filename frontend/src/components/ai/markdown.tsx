"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

const SECTION_STYLE: Record<string, string> = {
  verified: "border-positive/50 text-positive",
  calculation: "border-primary/50 text-primary",
  assumption: "border-warning/60 text-warning",
  opinion: "border-muted-foreground/40 text-muted-foreground",
};

function sectionClass(text: string) {
  const t = text.toLowerCase();
  const k = Object.keys(SECTION_STYLE).find((s) => t.startsWith(s));
  return k ? SECTION_STYLE[k] : "border-transparent text-foreground";
}

/** Renders model output. Raw HTML is not rendered (react-markdown default). [F1]-style citations become buttons. */
export function AnswerMarkdown({ text, onCite }: { text: string; onCite?: (id: string) => void }) {
  const withCites = text.replace(/\[([A-Z]\d{1,3})\]/g, "[$1](#src-$1)");
  return (
    <div className="answer text-[15px] leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h3 className="mt-3 mb-1 text-[16px] font-semibold">{children}</h3>,
          h2: ({ children }) => (
            <h3 className={cn("mt-4 mb-1.5 border-l-[3px] pl-2 text-[12px] font-bold uppercase tracking-wide first:mt-0", sectionClass(String(children)))}>
              {children}
            </h3>
          ),
          h3: ({ children }) => <h4 className="mt-3 mb-1 text-[14px] font-semibold">{children}</h4>,
          p: ({ children }) => <p className="my-1.5">{children}</p>,
          ul: ({ children }) => <ul className="my-1.5 list-disc space-y-1 pl-5 marker:text-muted-foreground">{children}</ul>,
          ol: ({ children }) => <ol className="my-1.5 list-decimal space-y-1 pl-5">{children}</ol>,
          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
          code: ({ children }) => <code className="rounded bg-elevated px-1 font-mono text-[13px]">{children}</code>,
          table: ({ children }) => (
            <div className="no-scrollbar my-2 overflow-x-auto rounded-xl border border-border/60">
              <table className="num w-max min-w-full text-[13px]">{children}</table>
            </div>
          ),
          th: ({ children }) => <th className="border-b border-border/60 bg-elevated px-2.5 py-1.5 text-left font-semibold whitespace-nowrap">{children}</th>,
          td: ({ children }) => <td className="border-b border-border/40 px-2.5 py-1.5 whitespace-nowrap">{children}</td>,
          a: ({ href, children }) => {
            if (href?.startsWith("#src-")) {
              const id = href.slice(5);
              return (
                <button
                  type="button"
                  onClick={() => onCite?.(id)}
                  className="mx-0.5 inline-flex -translate-y-px items-center rounded-md bg-accent px-1 py-px align-baseline font-mono text-[11px] font-semibold text-accent-foreground"
                >
                  {id}
                </button>
              );
            }
            return (
              <a href={href} target="_blank" rel="noreferrer noopener" className="text-primary underline">
                {children}
              </a>
            );
          },
          img: () => null,
        }}
      >
        {withCites}
      </ReactMarkdown>
    </div>
  );
}
