"use client";

import * as React from "react";
import useSWR from "swr";
import { Download, Laptop, Smartphone } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { Badge } from "@/components/ui/badge";
import { ErrorNote, PageHeader } from "@/components/page";
import { useAuth, useTheme } from "@/components/providers";
import { api } from "@/lib/api";
import { fmtRelative } from "@/lib/format";
import type { Preferences } from "@/lib/types";

type SessionRow = { id: number; user_agent: string; created_at: string; last_seen_at: string; current: boolean };

function device(ua: string) {
  if (/iPhone|iPad/.test(ua)) return "iPhone / iPad";
  if (/Android/.test(ua)) return "Android";
  if (/Mac OS X/.test(ua)) return "Mac";
  if (/Windows/.test(ua)) return "Windows";
  if (/Linux/.test(ua)) return "Linux";
  return ua ? ua.slice(0, 40) : "Unknown device";
}

export default function SettingsPage() {
  const { user } = useAuth();
  const { setTheme } = useTheme();
  const { data: prefs, mutate: mutatePrefs } = useSWR<Preferences>("/api/preferences");
  const { data: sessions, mutate: mutateSessions } = useSWR<SessionRow[]>("/api/auth/sessions");
  const [pw, setPw] = React.useState({ current_password: "", new_password: "", confirm: "" });
  const [pwMsg, setPwMsg] = React.useState<{ ok?: string; error?: unknown }>({});

  async function savePrefs(next: Preferences) {
    mutatePrefs(next, false);
    setTheme(next.theme);
    await api("/api/preferences", { method: "PUT", json: next }).catch(() => {});
    mutatePrefs();
  }

  async function changePassword(e: React.FormEvent) {
    e.preventDefault();
    if (pw.new_password !== pw.confirm) return setPwMsg({ error: new Error("New passwords do not match") });
    try {
      await api("/api/auth/password", { method: "POST", json: { current_password: pw.current_password, new_password: pw.new_password } });
      setPw({ current_password: "", new_password: "", confirm: "" });
      setPwMsg({ ok: "Password changed. Other devices were signed out." });
      mutateSessions();
    } catch (err) {
      setPwMsg({ error: err });
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Settings" subtitle={user ? `@${user.username}` : undefined} />

      <Card>
        <CardHeader>
          <CardTitle>Preferences</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {prefs && (
            <>
              <Field label="Theme">
                <Segmented
                  value={prefs.theme}
                  onChange={(theme) => savePrefs({ ...prefs, theme })}
                  options={[
                    { value: "dark", label: "Dark" },
                    { value: "light", label: "Light" },
                    { value: "system", label: "Auto" },
                  ]}
                />
              </Field>
              <Field label="Default currency for new transactions" htmlFor="ccy">
                <NativeSelect id="ccy" value={prefs.base_currency} onChange={(e) => savePrefs({ ...prefs, base_currency: e.target.value })}>
                  {["EUR", "USD", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN", "JPY", "CAD", "AUD", "BRL"].map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </NativeSelect>
              </Field>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Install on your phone</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-[14px]">
          <p>
            <b>iPhone (Safari):</b> tap Share → “Add to Home Screen”.
          </p>
          <p>
            <b>Android (Chrome):</b> tap ⋮ → “Install app” / “Add to Home screen”.
          </p>
          <p className="text-[12px] text-muted-foreground">
            Installation and offline mode need HTTPS (for example via Tailscale). See the README for the free setup.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Change password</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={changePassword} className="space-y-3">
            <Input type="password" autoComplete="current-password" placeholder="Current password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} required />
            <Input type="password" autoComplete="new-password" placeholder="New password (min. 10 characters)" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} required minLength={10} />
            <Input type="password" autoComplete="new-password" placeholder="Repeat new password" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} required />
            <ErrorNote error={pwMsg.error} />
            {pwMsg.ok && <p className="text-[13px] text-positive">{pwMsg.ok}</p>}
            <Button type="submit" variant="secondary" className="w-full">
              Update password
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Signed-in devices</CardTitle>
        </CardHeader>
        <ul className="divide-y divide-border/60 pb-1">
          {sessions?.map((s) => (
            <li key={s.id} className="flex items-center gap-3 px-4 py-3">
              {/iPhone|Android/.test(s.user_agent) ? <Smartphone className="size-4 text-muted-foreground" /> : <Laptop className="size-4 text-muted-foreground" />}
              <div className="flex-1">
                <p className="font-medium">
                  {device(s.user_agent)} {s.current && <Badge variant="positive">This device</Badge>}
                </p>
                <p className="text-[12px] text-muted-foreground">Active {fmtRelative(s.last_seen_at)}</p>
              </div>
              {!s.current && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-negative"
                  onClick={async () => {
                    await api(`/api/auth/sessions/${s.id}`, { method: "DELETE" });
                    mutateSessions();
                  }}
                >
                  Sign out
                </Button>
              )}
            </li>
          ))}
        </ul>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Your data</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="mb-3 text-[13px] text-muted-foreground">Download your watchlists, portfolios and notes as JSON. Only your own data is included.</p>
          <Button variant="secondary" className="w-full" asChild>
            <a href="/api/me/export" download>
              <Download /> Export my data
            </a>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
