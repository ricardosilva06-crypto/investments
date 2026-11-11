"use client";

import Link from "next/link";
import { ChevronRight, FileText, LineChart, Settings } from "lucide-react";
import { Sheet, SheetClose, SheetContent } from "@/components/ui/sheet";
import { Segmented } from "@/components/ui/segmented";
import { useTheme } from "@/components/providers";
import { api } from "@/lib/api";
import type { Preferences } from "@/lib/types";

const MENU = [
  { href: "/notes", label: "Notes & theses", icon: FileText },
  { href: "/prices", label: "Prices & exchange rates", icon: LineChart },
  { href: "/settings", label: "Settings & backup", icon: Settings },
];

export function AccountSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { theme, setTheme } = useTheme();

  async function changeTheme(t: Preferences["theme"]) {
    setTheme(t);
    try {
      await api("/api/preferences", { method: "PUT", json: { theme: t } });
    } catch {}
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent title="Menu">
        <div className="space-y-4 px-4 pb-6">
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
            {MENU.map(({ href, label, icon: Icon }) => (
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

          <p className="px-1 text-[12px] text-muted-foreground">
            Your data is stored only on this device, in this browser. Keep a backup (Settings → Export backup).
          </p>
        </div>
      </SheetContent>
    </Sheet>
  );
}
