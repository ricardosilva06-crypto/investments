"use client";

import * as React from "react";
import useSWR from "swr";
import { Copy, Database, Download, HardDrive, Loader2, Share2, Ticket, UserCheck, UserX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ErrorNote, PageHeader } from "@/components/page";
import { useAuth } from "@/components/providers";
import { PriceImportCard } from "@/components/price-import";
import { JobsCard, SecurityCard } from "@/components/admin-ops";
import { api } from "@/lib/api";
import { fmtDate, fmtInt, fmtRelative } from "@/lib/format";
import type { SystemStatus, User } from "@/lib/types";

type Invite = { id: number; code_hint: string; label: string; role: string; created_at: string; expires_at: string; used_at: string | null; revoked: boolean };
type Member = User & { is_active: boolean };
type Backup = { name: string; size_bytes: number; created_at: string };

function inviteState(i: Invite) {
  if (i.used_at) return <Badge variant="positive">Used</Badge>;
  if (i.revoked) return <Badge variant="muted">Revoked</Badge>;
  if (new Date(i.expires_at) < new Date()) return <Badge variant="muted">Expired</Badge>;
  return <Badge>Open</Badge>;
}

export default function AdminPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const { data: invites, mutate: mInv } = useSWR<Invite[]>(isAdmin ? "/api/admin/invites" : null);
  const { data: users, mutate: mUsers } = useSWR<Member[]>(isAdmin ? "/api/admin/users" : null);
  const { data: backups, mutate: mBackups } = useSWR<Backup[]>(isAdmin ? "/api/admin/backups" : null);
  const { data: status, mutate: mStatus } = useSWR<SystemStatus>("/api/system/status");
  const [label, setLabel] = React.useState("");
  const [newCode, setNewCode] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState<string | null>(null);
  const [error, setError] = React.useState<unknown>(null);
  const sec = status?.data_sources.find((s) => s.source === "sec_company_tickers_exchange");

  if (user && !isAdmin) return <ErrorNote error="Administrator access required." />;

  async function act(key: string, fn: () => Promise<unknown>) {
    setBusy(key);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }

  const shareText = (code: string) => `You're invited to Investor Intelligence. Open ${window.location.origin}/register and use invite code ${code}`;

  return (
    <div className="space-y-4">
      <PageHeader title="Administration" subtitle="Members, invites, data and backups" />
      <ErrorNote error={error} />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="size-4" /> SEC company list
          </CardTitle>
          {sec?.status === "ok" ? <Badge variant="positive">OK</Badge> : sec?.status === "error" ? <Badge variant="negative">Error</Badge> : <Badge variant="muted">Never synced</Badge>}
        </CardHeader>
        <CardContent className="space-y-2 text-[13px]">
          <p className="text-muted-foreground">
            {sec?.last_success_at ? `${fmtInt(sec.record_count)} securities · last success ${fmtDate(sec.last_success_at, true)}` : "Not loaded yet."}
          </p>
          {sec?.status === "error" && <p className="text-negative">{sec.message}</p>}
          <Button
            variant="secondary"
            className="w-full"
            disabled={busy === "sync"}
            onClick={() => act("sync", async () => {
              try {
                await api("/api/admin/sync/sec", { method: "POST" });
              } finally {
                await mStatus();
              }
            })}
          >
            {busy === "sync" && <Loader2 className="animate-spin" />} Sync from SEC EDGAR
          </Button>
          <p className="text-[11.5px] text-muted-foreground">One request per sync, at most once per hour. Requires II_SEC_USER_AGENT on the server (SEC fair-access policy).</p>
        </CardContent>
      </Card>

      <SecurityCard />
      <JobsCard />
      <PriceImportCard />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Ticket className="size-4" /> Invites
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <form
            className="flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              act("invite", async () => {
                const r = await api<{ code: string }>("/api/admin/invites", { method: "POST", json: { label } });
                setNewCode(r.code);
                setLabel("");
                mInv();
              });
            }}
          >
            <div className="flex-1">
              <Field label="Who is it for? (optional)" htmlFor="lbl">
                <Input id="lbl" value={label} onChange={(e) => setLabel(e.target.value)} maxLength={80} />
              </Field>
            </div>
            <Button type="submit" disabled={busy === "invite"}>
              Create
            </Button>
          </form>
          {newCode && (
            <div className="rounded-xl bg-primary/10 p-3 ring-1 ring-primary/30">
              <p className="text-[12px] text-muted-foreground">Single-use code, valid 7 days. It is shown only once.</p>
              <p className="my-1 font-mono text-lg font-semibold tracking-wider">{newCode}</p>
              <div className="grid grid-cols-2 gap-2">
                <Button variant="secondary" size="sm" onClick={() => navigator.clipboard?.writeText(newCode)}>
                  <Copy /> Copy
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => (navigator.share ? navigator.share({ text: shareText(newCode) }).catch(() => {}) : navigator.clipboard?.writeText(shareText(newCode)))}
                >
                  <Share2 /> Share
                </Button>
              </div>
            </div>
          )}
          <ul className="divide-y divide-border/60">
            {invites?.map((i) => (
              <li key={i.id} className="flex items-center gap-2 py-2.5 text-[13px]">
                <span className="font-mono">{i.code_hint}…</span>
                <span className="flex-1 truncate text-muted-foreground">{i.label || "—"}</span>
                {inviteState(i)}
                {!i.used_at && !i.revoked && new Date(i.expires_at) > new Date() && (
                  <Button variant="ghost" size="sm" className="text-negative" onClick={() => act(`rev${i.id}`, async () => { await api(`/api/admin/invites/${i.id}`, { method: "DELETE" }); mInv(); })}>
                    Revoke
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Members</CardTitle>
        </CardHeader>
        <ul className="divide-y divide-border/60 pb-1">
          {users?.map((u) => (
            <li key={u.id} className="flex items-center gap-3 px-4 py-3">
              <div className="flex-1">
                <p className="font-medium">
                  {u.display_name} {u.role === "admin" && <Badge>Admin</Badge>} {!u.is_active && <Badge variant="negative">Disabled</Badge>}
                </p>
                <p className="text-[12px] text-muted-foreground">
                  @{u.username} · joined {fmtDate(u.created_at)}
                </p>
              </div>
              {u.id !== user?.id && (
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={u.is_active ? "Disable account" : "Enable account"}
                  onClick={() => {
                    if (u.is_active && !confirm(`Disable ${u.display_name}? They will be signed out.`)) return;
                    act(`u${u.id}`, async () => { await api(`/api/admin/users/${u.id}`, { method: "PATCH", json: { is_active: !u.is_active } }); mUsers(); });
                  }}
                >
                  {u.is_active ? <UserX className="text-negative" /> : <UserCheck className="text-positive" />}
                </Button>
              )}
            </li>
          ))}
        </ul>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <HardDrive className="size-4" /> Backups
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Button variant="secondary" className="w-full" disabled={busy === "backup"} onClick={() => act("backup", async () => { await api("/api/admin/backups", { method: "POST" }); mBackups(); })}>
            {busy === "backup" && <Loader2 className="animate-spin" />} Create backup now
          </Button>
          <ul className="divide-y divide-border/60">
            {backups?.map((b) => (
              <li key={b.name} className="flex items-center gap-2 py-2.5 text-[13px]">
                <span className="flex-1">
                  {fmtDate(b.created_at, true)} <span className="text-muted-foreground">· {(b.size_bytes / 1024).toFixed(0)} KB</span>
                </span>
                <Button variant="ghost" size="icon" asChild aria-label="Download backup">
                  <a href={`/api/admin/backups/${encodeURIComponent(b.name)}`} download>
                    <Download />
                  </a>
                </Button>
              </li>
            ))}
            {backups?.length === 0 && <li className="py-2 text-[13px] text-muted-foreground">No backups yet.</li>}
          </ul>
          <p className="text-[11.5px] text-muted-foreground">
            Each backup is a zip with the database and all uploaded PDFs, made automatically every night. It contains every member’s data: store copies encrypted. The 14 most recent are kept in backend/data/backups. Last check {fmtRelative(status?.server_time)}.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
