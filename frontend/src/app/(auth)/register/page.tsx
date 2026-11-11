"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { ErrorNote } from "@/components/page";
import { api, clearOfflineCache } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const { refresh } = useAuth();
  const [form, setForm] = React.useState({ invite_code: "", username: "", display_name: "", password: "" });
  const [confirm, setConfirm] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (form.password !== confirm) return setError(new Error("Passwords do not match"));
    setBusy(true);
    setError(null);
    try {
      await clearOfflineCache();
      await api("/api/auth/register", { method: "POST", json: form });
      await refresh();
      router.replace("/");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label="Invite code" htmlFor="code">
        <Input id="code" placeholder="XXXX-XXXX-XXXX-XXXX" autoCapitalize="characters" autoCorrect="off" value={form.invite_code} onChange={set("invite_code")} required className="font-mono tracking-wider" />
      </Field>
      <Field label="Display name" htmlFor="dn">
        <Input id="dn" autoComplete="name" value={form.display_name} onChange={set("display_name")} required maxLength={80} />
      </Field>
      <Field label="Username" htmlFor="un">
        <Input id="un" autoComplete="username" autoCapitalize="none" autoCorrect="off" value={form.username} onChange={set("username")} required minLength={3} maxLength={40} />
      </Field>
      <Field label="Password (min. 10 characters)" htmlFor="pw">
        <Input id="pw" type="password" autoComplete="new-password" value={form.password} onChange={set("password")} required minLength={10} />
      </Field>
      <Field label="Repeat password" htmlFor="pw2">
        <Input id="pw2" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
      </Field>
      <ErrorNote error={error} />
      <Button type="submit" size="lg" className="w-full" disabled={busy}>
        {busy && <Loader2 className="animate-spin" />} Create account
      </Button>
      <p className="pt-2 text-center text-sm text-muted-foreground">
        Already registered?{" "}
        <Link href="/login" className="font-medium text-primary">
          Sign in
        </Link>
      </p>
    </form>
  );
}
