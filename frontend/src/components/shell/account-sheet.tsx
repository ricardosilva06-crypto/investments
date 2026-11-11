"use client";

import Link from "next/link";
import { ChevronRight, Database, FileText, FolderOpen, LogOut, Settings, Shield } from "lucide-react";
import { Sheet, SheetClose, SheetContent } from "@/components/ui/sheet";
import { Segmented } from "@/components/ui/segmented";
import { useAuth, useTheme } from "@/components/providers";
import { api } from "@/lib/api";
import type { Preferences } from "@/lib/types";

const MENU = [
  { href: "/notes", label: "Notes & theses", icon: FileText, admin: false },
  { href: "/documents", label: "Documents (PDF)", icon: FolderOpen, admin: false },
  { href: "/sources", label: "Data sources", icon: Database, admin: false },
  { href: "/settings", label: "Settings & security", icon: Settings, admin: false },
  { href: "/admin", label: "Administration", icon: Shield, admin: true },
];

export function AccountSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  if (!user) return null;

  async function changeTheme(t: Preferences["theme"]) {
    setTheme(t);
    try {
      const p = await api<Preferences>("/api/preferences");
      await api("/api/preferences", { method: "PUT", json: { ...p, theme: t } });
    } catch {}
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent title="Account">
        <div className="space-y-4 px-4 pb-6">
          <div className="flex items-center gap-3 rounded-2xl bg-elevated p-3.5">
            <span className="grid size-12 place-items-center rounded-full bg-primary/15 text-lg font-semibold text-primary">
              {user.display_name.slice(0, 1).toUpperCase()}
            </span>
            <div className="min-w-0">
              <p className="truncate font-semibold">{user.display_name}</p>
              <p className="truncate text-[13px] text-muted-foreground">
                @{user.username} · {user.role === "admin" ? "Administrator" : "Member"}
              </p>
            </div>
          </div>

          <div>
            <p className="mb-1.5 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">Appearance</p>
            <Segmented
              value={theme}
              onChange={changeTheme}
              options={[
                { value: "dark", label: "Dark" },
                { value: "light", label: "Light" },
                { value: "system", label: "Auto" },
              ]}
            />
          </div>

          <ul className="divide-y divide-border/60 overflow-hidden rounded-2xl border border-border/60">
            {MENU.filter((m) => !m.admin || user.role === "admin").map(({ href, label, icon: Icon }) => (
              <li key={href}>
                <SheetClose asChild>
                  <Link href={href} className="flex items-center gap-3 px-3.5 py-3.5 active:bg-muted">
                    <Icon className="size-[18px] text-muted-foreground" />
                    <span className="flex-1 font-medium">{label}</span>
                    <ChevronRight className="size-4 text-muted-foreground" />
                  </Link>
                </SheetClose>
              </li>
            ))}
          </ul>

          <button
            onClick={logout}
            className="flex w-full items-center justify-center gap-2 rounded-2xl bg-negative/10 py-3.5 font-medium text-negative active:scale-[0.98]"
          >
            <LogOut className="size-4" /> Sign out
          </button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
