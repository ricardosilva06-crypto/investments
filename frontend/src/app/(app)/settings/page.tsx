"use client";

import * as React from "react";
import useSWR, { useSWRConfig } from "swr";
import { HardDriveDownload, HardDriveUpload, Loader2, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { Badge } from "@/components/ui/badge";
import { ErrorNote, PageHeader } from "@/components/page";
import { useTheme } from "@/components/providers";
import { api } from "@/lib/api";
import { fmtRelative } from "@/lib/format";
import { backupFileName, buildBackup, checkBackup, lastBackupAt, markBackedUp, restoreBackup } from "@/lib/local/backup";
import { DB_NAME, resetDbConnection } from "@/lib/local/db";
import type { Preferences } from "@/lib/types";

const CURRENCIES = ["EUR", "USD", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN", "JPY", "CAD", "AUD", "BRL"];

function fmtBytes(n: number) {
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(1)} GB`;
}

function useStorageInfo() {
  const [info, setInfo] = React.useState<{ persisted: boolean | null; usage: number | null; quota: number | null }>({ persisted: null, usage: null, quota: null });
  React.useEffect(() => {
    (async () => {
      try {
        const persisted = navigator.storage?.persisted ? await navigator.storage.persisted() : null;
        const est = navigator.storage?.estimate ? await navigator.storage.estimate() : null;
        setInfo({ persisted, usage: est?.usage ?? null, quota: est?.quota ?? null });
      } catch {}
    })();
  }, []);
  return info;
}

function BackupCard() {
  const { mutate } = useSWRConfig();
  const { data: last, mutate: mutateLast } = useSWR("local:last-backup", () => lastBackupAt().then((v) => v ?? null));
  const [busy, setBusy] = React.useState<"export" | "import" | null>(null);
  const [error, setError] = React.useState<unknown>(null);
  const [msg, setMsg] = React.useState<string | null>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);

  async function exportBackup() {
    setBusy("export");
    setError(null);
    setMsg(null);
    try {
      const json = JSON.stringify(await buildBackup());
      const file = new File([json], backupFileName(), { type: "application/json" });
      // iPhone: the share sheet offers "Save to Files" (e.g. iCloud Drive). Elsewhere: a normal download.
      if (navigator.canShare?.({ files: [file] })) {
        try {
          await navigator.share({ files: [file], title: "Investor Intelligence backup" });
        } catch (e) {
          if ((e as Error).name === "AbortError") return; // user closed the share sheet: no backup made
          throw e;
        }
      } else {
        const url = URL.createObjectURL(file);
        const a = document.createElement("a");
        a.href = url;
        a.download = file.name;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 10_000);
      }
      await markBackedUp();
      await mutateLast();
      mutate("/api/dashboard");
      setMsg(`Backup created (${fmtBytes(file.size)}). Keep it somewhere safe, e.g. iCloud Drive.`);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }

  async function importBackup(file: File) {
    setError(null);
    setMsg(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(await file.text());
      const counts = checkBackup(parsed);
      const summary = `${counts.portfolios} portfolios, ${counts.transactions} transactions, ${counts.watchlists} watchlists, ${counts.notes} notes, ${counts.prices} price days`;
      if (!confirm(`Replace ALL data on this device with this backup?\n\n${summary}\n\nThis cannot be undone.`)) return;
      setBusy("import");
      await restoreBackup(parsed);
      await mutate(() => true, undefined, { revalidate: true });
      await mutateLast();
      setMsg(`Backup restored: ${summary}.`);
    } catch (e) {
      setError(e instanceof SyntaxError ? new Error("This file is not a valid backup (not JSON).") : e);
    } finally {
      setBusy(null);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <Card id="backup">
      <CardHeader>
        <CardTitle>Backup</CardTitle>
        <Badge variant={last ? "muted" : "warning"}>{last ? `Last ${fmtRelative(last)}` : "Never"}</Badge>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-[13px] text-muted-foreground">
          Your data exists only on this phone, in this browser. If you clear Safari&apos;s website data, remove the app or change phone, it is gone, unless you have a backup.
          Export one regularly and save it to Files / iCloud Drive.
        </p>
        <Button className="w-full" onClick={exportBackup} disabled={!!busy}>
          {busy === "export" ? <Loader2 className="animate-spin" /> : <HardDriveDownload />} Export backup
        </Button>
        <Button variant="secondary" className="w-full" onClick={() => fileRef.current?.click()} disabled={!!busy}>
          {busy === "import" ? <Loader2 className="animate-spin" /> : <HardDriveUpload />} Restore from backup…
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept="application/json,.json"
          className="hidden"
          aria-label="Backup file"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) importBackup(f);
          }}
        />
        <ErrorNote error={error} />
        {msg && <p className="text-[13px] text-positive">{msg}</p>}
      </CardContent>
    </Card>
  );
}

export default function SettingsPage() {
  const { setTheme } = useTheme();
  const { data: prefs, mutate: mutatePrefs } = useSWR<Preferences>("/api/preferences");
  const storage = useStorageInfo();
  const [name, setName] = React.useState<string | null>(null);

  async function savePrefs(next: Preferences) {
    mutatePrefs(next, false);
    setTheme(next.theme);
    await api("/api/preferences", { method: "PUT", json: next }).catch(() => {});
    mutatePrefs();
  }

  async function deleteEverything() {
    if (!confirm("Delete ALL data stored by this app on this device? Export a backup first if you may need it.")) return;
    if (!confirm("Really delete everything? This cannot be undone.")) return;
    resetDbConnection();
    await new Promise<void>((res) => {
      const r = indexedDB.deleteDatabase(DB_NAME);
      r.onsuccess = r.onerror = r.onblocked = () => res();
    });
    location.reload();
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Settings" subtitle="Everything stays on this device." />

      <Card>
        <CardHeader>
          <CardTitle>Preferences</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {prefs && (
            <>
              <Field label="Your first name (for the greeting)" htmlFor="dn">
                <Input
                  id="dn"
                  value={name ?? prefs.display_name}
                  onChange={(e) => setName(e.target.value)}
                  onBlur={() => name !== null && savePrefs({ ...prefs, display_name: name })}
                  maxLength={40}
                  autoComplete="given-name"
                />
              </Field>
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
              <Field label="Base currency (new transactions, portfolio total)" htmlFor="ccy">
                <NativeSelect id="ccy" value={prefs.base_currency} onChange={(e) => savePrefs({ ...prefs, base_currency: e.target.value })}>
                  {CURRENCIES.map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </NativeSelect>
              </Field>
            </>
          )}
        </CardContent>
      </Card>

      <BackupCard />

      <Card>
        <CardHeader>
          <CardTitle>Install on your phone</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-[14px]">
          <p>
            <b>iPhone (Safari):</b> tap Share → “Add to Home Screen”. Then always open the app from that icon: its data is separate from Safari&apos;s.
          </p>
          <p>
            <b>Android (Chrome):</b> tap ⋮ → “Install app”.
          </p>
          <p className="text-[12px] text-muted-foreground">After the first visit the app works offline.</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Storage on this device</CardTitle>
          {storage.persisted !== null && <Badge variant={storage.persisted ? "positive" : "muted"}>{storage.persisted ? "Protected" : "Standard"}</Badge>}
        </CardHeader>
        <CardContent className="space-y-3 text-[13px] text-muted-foreground">
          <p>
            {storage.usage !== null ? `Using ${fmtBytes(storage.usage)}${storage.quota ? ` of ${fmtBytes(storage.quota)} available to this app` : ""}. ` : ""}
            {storage.persisted
              ? "The browser has agreed not to clear this data automatically."
              : "The browser may clear website data when space is very low or if the app is unused for a long time; backups protect you."}
          </p>
          <Button variant="destructive" className="w-full" onClick={deleteEverything}>
            <Trash2 /> Delete all data on this device
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
