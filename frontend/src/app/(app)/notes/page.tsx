"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { FileText, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/input";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorNote, PageHeader } from "@/components/page";
import { api } from "@/lib/api";
import { fmtRelative } from "@/lib/format";
import type { Note } from "@/lib/types";

export default function NotesPage() {
  const router = useRouter();
  const params = useSearchParams();
  const { data, error, mutate } = useSWR<Note[]>("/api/notes");
  const openId = Number(params.get("id")) || null;
  const isNew = params.get("new") === "1";
  const presetTicker = params.get("t") ?? "";
  const { data: single } = useSWR<Note>(openId && !data?.some((n) => n.id === openId) ? `/api/notes/${openId}` : null);
  const editing = openId ? (data?.find((n) => n.id === openId) ?? single) : undefined;
  const open = isNew || !!editing;

  const close = () => router.replace("/notes", { scroll: false });
  const initial = editing
    ? { title: editing.title, body: editing.body, ticker: editing.security?.ticker ?? "" }
    : { title: presetTicker ? `${presetTicker} thesis` : "", body: "", ticker: presetTicker };

  return (
    <div>
      <PageHeader
        title="Notes"
        subtitle="Stored on this device only."
        action={
          <Button size="icon" variant="secondary" onClick={() => router.replace("/notes?new=1")} aria-label="New note">
            <Plus className="size-5" />
          </Button>
        }
      />
      <ErrorNote error={error} />
      {!data && !error && <Skeleton className="h-40" />}
      {data?.length === 0 && (
        <EmptyState icon={FileText} title="No notes yet">
          Capture your thesis, risks and what would change your mind.
        </EmptyState>
      )}
      <ul className="space-y-2">
        {data?.map((n) => (
          <li key={n.id}>
            <button onClick={() => router.replace(`/notes?id=${n.id}`)} className="w-full rounded-2xl border border-border/60 bg-card p-3.5 text-left active:scale-[0.99]">
              <div className="flex items-center gap-2">
                <span className="flex-1 truncate font-semibold">{n.title}</span>
                {n.security && <Badge>{n.security.ticker}</Badge>}
              </div>
              {n.body && <p className="mt-1 line-clamp-2 text-[13px] text-muted-foreground">{n.body}</p>}
              <p className="mt-1 text-[11px] text-muted-foreground">
                Edited {fmtRelative(n.updated_at)}
              </p>
            </button>
          </li>
        ))}
      </ul>

      <Sheet open={open} onOpenChange={(o) => !o && close()}>
        <SheetContent title={editing ? "Edit note" : "New note"} full>
          <NoteEditor
            key={editing ? `n${editing.id}` : `new-${presetTicker}`}
            initial={initial}
            note={editing}
            onSaved={async () => {
              await mutate();
              close();
            }}
          />
        </SheetContent>
      </Sheet>
    </div>
  );
}

function NoteEditor({
  initial,
  note,
  onSaved,
}: {
  initial: { title: string; body: string; ticker: string };
  note?: Note;
  onSaved: () => Promise<void>;
}) {
  const [form, setForm] = React.useState(initial);
  const [opError, setOpError] = React.useState<unknown>(null);
  const [busy, setBusy] = React.useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setOpError(null);
    try {
      const json = { ...form, ticker: form.ticker.trim() || null };
      if (note) await api(`/api/notes/${note.id}`, { method: "PUT", json });
      else await api("/api/notes", { method: "POST", json });
      await onSaved();
    } catch (err) {
      setOpError(err);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!note || !confirm(`Delete “${note.title}”?`)) return;
    try {
      await api(`/api/notes/${note.id}`, { method: "DELETE" });
      await onSaved();
    } catch (err) {
      setOpError(err);
    }
  }

  return (
    <form onSubmit={save} className="space-y-3 px-4 pb-6">
      <Field label="Title" htmlFor="nt">
        <Input id="nt" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} required maxLength={160} />
      </Field>
      <Field label="Linked ticker (optional)" htmlFor="tk">
        <Input id="tk" value={form.ticker} onChange={(e) => setForm({ ...form, ticker: e.target.value.toUpperCase() })} autoCapitalize="characters" autoCorrect="off" maxLength={20} />
      </Field>
      <Field label="Note" htmlFor="nb">
        <Textarea
          id="nb"
          value={form.body}
          onChange={(e) => setForm({ ...form, body: e.target.value })}
          className="min-h-[45dvh]"
          placeholder={"Thesis\n\nKey risks\n\nWhat would change my mind"}
        />
      </Field>
      <ErrorNote error={opError} />
      <Button type="submit" className="w-full" disabled={busy}>
        Save
      </Button>
      {note && (
        <Button type="button" variant="destructive" className="w-full" onClick={remove}>
          <Trash2 /> Delete note
        </Button>
      )}
    </form>
  );
}
