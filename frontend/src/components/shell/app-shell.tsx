"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { requestPersistence } from "@/lib/local/backup";
import { AccountSheet } from "./account-sheet";
import { BottomNav } from "./bottom-nav";
import { Logo } from "./logo";
import { SearchSheet } from "./search-sheet";

type ShellCtx = { openSearch: () => void };
const ShellContext = React.createContext<ShellCtx>({ openSearch: () => {} });
export const useShell = () => React.useContext(ShellContext);

function TopBar({ onSearch, onMenu }: { onSearch: () => void; onMenu: () => void }) {
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
        <Button variant="ghost" size="icon" onClick={onMenu} aria-label="Menu" className="rounded-full">
          <Menu className="size-5" />
        </Button>
      </div>
    </header>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [search, setSearch] = React.useState(false);
  const [menu, setMenu] = React.useState(false);

  // Data lives only on this device: ask the browser not to evict it under storage pressure.
  React.useEffect(() => {
    requestPersistence();
  }, []);

  return (
    <ShellContext.Provider value={{ openSearch: () => setSearch(true) }}>
      <TopBar onSearch={() => setSearch(true)} onMenu={() => setMenu(true)} />
      <main key={pathname} className="animate-page mx-auto w-full max-w-xl flex-1 px-safe pt-4 pb-[calc(84px+env(safe-area-inset-bottom))]">
        {children}
      </main>
      <BottomNav />
      <SearchSheet open={search} onOpenChange={setSearch} />
      <AccountSheet open={menu} onOpenChange={setMenu} />
    </ShellContext.Provider>
  );
}
