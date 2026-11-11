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
import { Segmented } from "@/components/ui/segmented";
import { api } from "@/lib/api";
import { fmtRelative } from "@/lib/format";
import type { Note } from "@/lib/types";

export default function NotesPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [scope, setScope] = React.useState<"mine" | "shared">("mine");
  const { data, error, mutate } = useSWR<Note[]>(`/api/notes?scope=${scope}`);
  const openId = Number(params.get("id")) || null;
  const isNew = params.get("new") === "1";
  const presetTicker = params.get("t") ?? "";
  const { data: single } = useSWR<Note>(openId && !data?.some((n) => n.id === openId) ? `/api/notes/${openId}` : null);
  const editing = openId ? (data?.find((n) => n.id === openId) ?? single) : undefined;
  const readOnly = editing ? !editing.is_mine : false;
  const open = isNew || !!editing;

  const close = () => router.replace("/notes", { scroll: false });
  const initial = editing
    ? { title: editing.title, body: editing.body, ticker: editing.security?.ticker ?? "" }
    : { title: presetTicker ? `${presetTicker} thesis` : "", body: "", ticker: presetTicker };
  const initialShared = editing?.is_shared ?? false;

  return (
    <div>
      <PageHeader
        title="Notes"
        subtitle="Private by default. Share a note with members only if you choose to."
        action={
          <Button size="icon" variant="secondary" onClick={() => router.replace("/notes?new=1")} aria-label="New note">
            <Plus className="size-5" />
          </Button>
        }
      />
      <Segmented
        className="mb-3"
        value={scope}
        onChange={setScope}
        options={[
          { value: "mine", label: "My notes" },
          { value: "shared", label: "Shared by members" },
        ]}
      />
      <ErrorNote error={error} />
      {!data && !error && <Skeleton className="h-40" />}
      {data?.length === 0 && (
        <EmptyState icon={FileText} title={scope === "mine" ? "No notes yet" : "Nothing shared yet"}>
          {scope === "mine" ? "Capture your thesis, risks and what would change your mind." : "When a member shares a note, it appears here (read-only)."}
        </EmptyState>
      )}
      <ul className="space-y-2">
        {data?.map((n) => (
          <li key={n.id}>
            <button onClick={() => router.replace(`/notes?id=${n.id}`)} className="w-full rounded-2xl border border-border/60 bg-card p-3.5 text-left active:scale-[0.99]">
              <div className="flex items-center gap-2">
                <span className="flex-1 truncate font-semibold">{n.title}</span>
                {n.security && <Badge>{n.security.ticker}</Badge>}
                {n.is_mine && n.is_shared && <Badge variant="positive">Shared</Badge>}
              </div>
              {n.body && <p className="mt-1 line-clamp-2 text-[13px] text-muted-foreground">{n.body}</p>}
              <p className="mt-1 text-[11px] text-muted-foreground">
                {n.author ? `${n.author} · ` : ""}Edited {fmtRelative(n.updated_at)}
              </p>
            </button>
          </li>
        ))}
      </ul>

      <Sheet open={open} onOpenChange={(o) => !o && close()}>
        <SheetContent title={readOnly ? `Shared by ${editing?.author ?? "a member"}` : editing ? "Edit note" : "New note"} full>
          {readOnly && editing ? (
            <div className="space-y-2 px-4 pb-6">
              <h2 className="text-xl font-semibold">{editing.title}</h2>
              {editing.security && <Badge>{editing.security.ticker}</Badge>}
              <p className="text-[12px] text-muted-foreground">Read-only · edited {fmtRelative(editing.updated_at)}</p>
              <div className="pt-2 text-[15px] leading-relaxed whitespace-pre-wrap">{editing.body || "No content"}</div>
            </div>
          ) : (
          <NoteEditor
            key={editing ? `n${editing.id}` : `new-${presetTicker}`}
            initial={initial}
            initialShared={initialShared}
            note={editing}
            onSaved={async () => {
              await mutate();
              close();
            }}
          />
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

function NoteEditor({
  initial,
  initialShared,
  note,
  onSaved,
}: {
  initial: { title: string; body: string; ticker: string };
  initialShared: boolean;
  note?: Note;
  onSaved: () => Promise<void>;
}) {
  const [form, setForm] = React.useState(initial);
  const [shared, setShared] = React.useState(initialShared);
  const [opError, setOpError] = React.useState<unknown>(null);
  const [busy, setBusy] = React.useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setOpError(null);
    try {
      const json = { ...form, ticker: form.ticker.trim() || null, is_shared: shared };
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
      <Field label="Linked ticker (optional, SEC list)" htmlFor="tk">
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
      <label className="flex items-start gap-2 rounded-xl bg-elevated p-3 text-[14px]">
        <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} className="mt-0.5 size-4 accent-[var(--primary)]" />
        <span>
          Share with members
          <span className="block text-[12px] text-muted-foreground">Other members can read (not edit) this note, with your name. Untick to make it private again.</span>
        </span>
      </label>
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
