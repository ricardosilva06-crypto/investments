"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Briefcase, Eye, FileText, House } from "lucide-react";
import { cn } from "@/lib/utils";

export const NAV = [
  { href: "/", label: "Home", icon: House },
  { href: "/watchlist", label: "Watchlist", icon: Eye },
  { href: "/portfolio", label: "Portfolio", icon: Briefcase },
  { href: "/notes", label: "Notes", icon: FileText },
] as const;

export function BottomNav() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-border/60 bg-nav pb-safe backdrop-blur-xl backdrop-saturate-150"
    >
      <ul className="mx-auto grid max-w-xl grid-cols-4">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex h-[58px] flex-col items-center justify-center gap-1 text-[10.5px] font-medium text-muted-foreground transition-colors active:scale-95",
                  active && "text-primary",
                )}
              >
                <span className={cn("grid h-7 w-12 place-items-center rounded-full transition-colors", active && "bg-primary/12")}>
                  <Icon className="size-[21px]" strokeWidth={active ? 2.3 : 1.8} />
                </span>
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
