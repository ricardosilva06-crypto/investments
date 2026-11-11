import * as React from "react";
import { cn } from "@/lib/utils";

export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="mb-4 flex items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="truncate text-[28px] font-bold tracking-tight">{title}</h1>
        {subtitle ? <p className="mt-0.5 text-[13px] text-muted-foreground">{subtitle}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function Section({ title, action, children, className }: { title: string; action?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("mt-6", className)}>
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-[15px] font-semibold">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

export function EmptyState({ icon: Icon, title, children }: { icon: React.ElementType; title: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-border px-6 py-8 text-center">
      <span className="grid size-11 place-items-center rounded-2xl bg-accent text-accent-foreground">
        <Icon className="size-5" />
      </span>
      <p className="font-semibold">{title}</p>
      {children ? <div className="text-[13px] text-muted-foreground">{children}</div> : null}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="rounded-xl bg-negative/10 px-3 py-2 text-[13px] text-negative">
      {error instanceof Error ? error.message : String(error)}
    </p>
  );
}

export function SourceLine({ children }: { children: React.ReactNode }) {
  return <p className="mt-2 text-[11.5px] leading-snug text-muted-foreground">{children}</p>;
}
