"use client";

import { useRouter } from "next/navigation";
import useSWR from "swr";
import { BellOff, CheckCheck } from "lucide-react";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { fmtRelative } from "@/lib/format";
import type { Notification } from "@/lib/types";
import { cn } from "@/lib/utils";

export function useNotifications() {
  return useSWR<Notification[]>("/api/notifications", { refreshInterval: 60_000 });
}

export function NotificationsSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const router = useRouter();
  const { data, mutate } = useNotifications();
  const unread = data?.filter((n) => !n.read_at).length ?? 0;

  async function openItem(n: Notification) {
    if (!n.read_at) await api(`/api/notifications/${n.id}/read`, { method: "POST" }).catch(() => {});
    mutate();
    if (n.link) {
      onOpenChange(false);
      router.push(n.link);
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent title="Notifications" description={unread ? `${unread} unread` : "You're all caught up"}>
        <div className="px-4 pb-6">
          {unread > 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="mb-2 -ml-2 text-primary"
              onClick={async () => {
                await api("/api/notifications/read-all", { method: "POST" });
                mutate();
              }}
            >
              <CheckCheck /> Mark all as read
            </Button>
          )}
          {data && data.length === 0 && (
            <div className="flex flex-col items-center gap-2 py-12 text-center text-sm text-muted-foreground">
              <BellOff className="size-6" />
              No notifications yet. Account and data-sync events appear here; price alerts arrive in Phase 5.
            </div>
          )}
          <ul className="space-y-2">
            {data?.map((n) => (
              <li key={n.id}>
                <button
                  onClick={() => openItem(n)}
                  className={cn("w-full rounded-2xl border border-border/60 p-3.5 text-left active:bg-muted", !n.read_at && "bg-accent/40")}
                >
                  <div className="flex items-start justify-between gap-3">
                    <span className="font-semibold">{n.title}</span>
                    <span className="shrink-0 text-[12px] text-muted-foreground">{fmtRelative(n.created_at)}</span>
                  </div>
                  {n.body && <p className="mt-0.5 text-[13px] text-muted-foreground">{n.body}</p>}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </SheetContent>
    </Sheet>
  );
}
