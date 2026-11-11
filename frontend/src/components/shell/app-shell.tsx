"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Bell, CloudOff, Search, WifiOff } from "lucide-react";
import { useAuth } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { onCacheStatus } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { AccountSheet } from "./account-sheet";
import { BottomNav } from "./bottom-nav";
import { Logo } from "./logo";
import { NotificationsSheet, useNotifications } from "./notifications-sheet";
import { SearchSheet } from "./search-sheet";

type ShellCtx = { openSearch: () => void };
const ShellContext = React.createContext<ShellCtx>({ openSearch: () => {} });
export const useShell = () => React.useContext(ShellContext);

function subscribeOnline(cb: () => void) {
  window.addEventListener("online", cb);
  window.addEventListener("offline", cb);
  return () => {
    window.removeEventListener("online", cb);
    window.removeEventListener("offline", cb);
  };
}

function useOnline() {
  return React.useSyncExternalStore(subscribeOnline, () => navigator.onLine, () => true);
}

function OfflineBanner() {
  const online = useOnline();
  const [cachedAt, setCachedAt] = React.useState<string | null>(null);
  React.useEffect(() => {
    const off = onCacheStatus(setCachedAt);
    return () => {
      off();
    };
  }, []);
  if (online && !cachedAt) return null;
  return (
    <div role="status" className="flex items-center gap-2 bg-warning/15 px-4 py-2 text-[13px] font-medium text-warning">
      {online ? <CloudOff className="size-4 shrink-0" /> : <WifiOff className="size-4 shrink-0" />}
      <span>
        {online ? "Server unreachable." : "You are offline."}{" "}
        {cachedAt ? `Showing data saved ${fmtDate(cachedAt, true)}.` : "Changes cannot be saved."}
      </span>
    </div>
  );
}

function TopBar({ onSearch, onBell, onAccount }: { onSearch: () => void; onBell: () => void; onAccount: () => void }) {
  const { user } = useAuth();
  const { data } = useNotifications();
  const unread = data?.filter((n) => !n.read_at).length ?? 0;
  return (
    <header className="sticky top-0 z-30 border-b border-border/50 bg-nav pt-safe backdrop-blur-xl backdrop-saturate-150">
      <div className="mx-auto flex h-14 max-w-xl items-center gap-2 px-safe">
        <Link href="/" className="flex items-center gap-2 pr-1" aria-label="Investor Intelligence home">
          <Logo className="size-8" />
        </Link>
        <button
          onClick={onSearch}
          className="flex h-10 flex-1 items-center gap-2 rounded-xl bg-elevated px-3 text-left text-[15px] text-muted-foreground active:scale-[0.99]"
          aria-label="Open search"
        >
          <Search className="size-4" />
          Search
        </button>
        <Button variant="ghost" size="icon" onClick={onBell} aria-label={`Notifications${unread ? ` (${unread} unread)` : ""}`} className="relative rounded-full">
          <Bell className="size-5" />
          {unread > 0 && (
            <span className="absolute top-1.5 right-1.5 grid min-w-4 place-items-center rounded-full bg-negative px-1 text-[10px] font-bold leading-4 text-white">
              {unread > 9 ? "9+" : unread}
            </span>
          )}
        </Button>
        <button
          onClick={onAccount}
          aria-label="Account and menu"
          className="grid size-9 place-items-center rounded-full bg-primary/15 text-[15px] font-semibold text-primary active:scale-95"
        >
          {user?.display_name.slice(0, 1).toUpperCase()}
        </button>
      </div>
    </header>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, unreachable, refresh } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [search, setSearch] = React.useState(false);
  const [bell, setBell] = React.useState(false);
  const [account, setAccount] = React.useState(false);

  React.useEffect(() => {
    if (user === null && !unreachable) router.replace("/login");
  }, [user, unreachable, router]);

  if (unreachable) {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-4 px-8 text-center">
        <Logo className="size-14" />
        <p className="text-lg font-semibold">Cannot reach your Investor Intelligence server</p>
        <p className="text-sm text-muted-foreground">
          Check that the server is running and that this phone is on the same network or VPN.
        </p>
        <Button onClick={() => refresh()}>Try again</Button>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="grid min-h-dvh place-items-center">
        <Logo className="size-12 animate-pulse" />
      </div>
    );
  }

  return (
    <ShellContext.Provider value={{ openSearch: () => setSearch(true) }}>
      <TopBar onSearch={() => setSearch(true)} onBell={() => setBell(true)} onAccount={() => setAccount(true)} />
      <OfflineBanner />
      <main key={pathname} className="animate-page mx-auto w-full max-w-xl flex-1 px-safe pt-4 pb-[calc(84px+env(safe-area-inset-bottom))]">
        {children}
      </main>
      <BottomNav />
      <SearchSheet open={search} onOpenChange={setSearch} />
      <NotificationsSheet open={bell} onOpenChange={setBell} />
      <AccountSheet open={account} onOpenChange={setAccount} />
    </ShellContext.Provider>
  );
}
