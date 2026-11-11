"use client";

import * as React from "react";
import { SWRConfig } from "swr";
import { api, fetcher } from "@/lib/api";
import { withBase } from "@/lib/base";
import type { Preferences } from "@/lib/types";

type Theme = Preferences["theme"];
const THEME_KEY = "ii-theme";

type ThemeCtx = { theme: Theme; setTheme: (t: Theme) => void };
const ThemeContext = React.createContext<ThemeCtx | null>(null);

export function useTheme() {
  const c = React.useContext(ThemeContext);
  if (!c) throw new Error("useTheme outside provider");
  return c;
}

export function applyTheme(theme: Theme) {
  const dark = theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
  const meta = document.querySelector('meta[name="theme-color"]');
  meta?.setAttribute("content", dark ? "#0d0f13" : "#f8f9fb");
}

function readStoredTheme(): Theme {
  try {
    const t = localStorage.getItem(THEME_KEY);
    if (t === "light" || t === "dark" || t === "system") return t;
  } catch {}
  return "dark";
}

function ThemeProvider({ children }: { children: React.ReactNode }) {
  // localStorage mirrors the theme so it applies before first paint (see layout.tsx);
  // the saved preference in on-device storage (part of backups) is the source of truth.
  const [theme, setThemeState] = React.useState<Theme>(() => (typeof window === "undefined" ? "dark" : readStoredTheme()));

  React.useEffect(() => {
    applyTheme(theme);
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const fn = () => applyTheme("system");
    mq.addEventListener("change", fn);
    return () => mq.removeEventListener("change", fn);
  }, [theme]);

  const setTheme = React.useCallback((t: Theme) => {
    setThemeState(t);
    try {
      localStorage.setItem(THEME_KEY, t);
    } catch {}
  }, []);

  React.useEffect(() => {
    api<Preferences>("/api/preferences")
      .then((p) => setTheme(p.theme))
      .catch(() => {});
  }, [setTheme]);

  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>;
}

function ServiceWorker() {
  React.useEffect(() => {
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register(withBase("/sw.js"), { scope: withBase("/"), updateViaCache: "none" }).catch(() => {});
  }, []);
  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig value={{ fetcher, keepPreviousData: true, errorRetryCount: 1, revalidateOnFocus: false }}>
      <ThemeProvider>
        <ServiceWorker />
        {children}
      </ThemeProvider>
    </SWRConfig>
  );
}
