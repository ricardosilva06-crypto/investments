"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import useSWR, { SWRConfig, useSWRConfig } from "swr";
import { ApiError, api, clearOfflineCache, fetcher } from "@/lib/api";
import type { Preferences, User } from "@/lib/types";

type Theme = Preferences["theme"];
const THEME_KEY = "ii-theme";

type AuthCtx = {
  user: User | null | undefined; // undefined = loading, null = signed out
  unreachable: boolean; // server could not be reached and nothing is cached
  refresh: () => Promise<unknown>;
  logout: () => Promise<void>;
};
const AuthContext = React.createContext<AuthCtx | null>(null);

type ThemeCtx = { theme: Theme; setTheme: (t: Theme) => void };
const ThemeContext = React.createContext<ThemeCtx | null>(null);

export function useAuth() {
  const c = React.useContext(AuthContext);
  if (!c) throw new Error("useAuth outside provider");
  return c;
}

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
  // Theme is only rendered inside client-only UI (sheets/settings), so reading
  // localStorage during the first client render cannot cause a hydration mismatch.
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

  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>;
}

function AuthProvider({ children }: { children: React.ReactNode }) {
  const { data, error, mutate } = useSWR<User>("/api/auth/me", fetcher, {
    shouldRetryOnError: false,
    revalidateOnFocus: true,
  });
  const signedOut = error instanceof ApiError && error.status === 401;
  const unreachable = !!error && !signedOut && !data;
  const user = signedOut ? null : data;
  const { setTheme } = useTheme();
  const router = useRouter();
  const { mutate: globalMutate } = useSWRConfig();

  // Sync the theme with the server-side preference once signed in.
  React.useEffect(() => {
    if (!data) return;
    api<Preferences>("/api/preferences")
      .then((p) => setTheme(p.theme))
      .catch(() => {});
  }, [data, setTheme]);

  const logout = React.useCallback(async () => {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } catch {}
    await clearOfflineCache();
    // Forget every cached response in memory, then re-check the session.
    await globalMutate(() => true, undefined, { revalidate: false });
    await mutate();
    router.replace("/login");
  }, [mutate, globalMutate, router]);

  return (
    <AuthContext.Provider value={{ user, unreachable, refresh: () => mutate(), logout }}>
      {children}
    </AuthContext.Provider>
  );
}

function ServiceWorker() {
  React.useEffect(() => {
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" }).catch(() => {});
  }, []);
  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig value={{ fetcher, keepPreviousData: true, errorRetryCount: 2 }}>
      <ThemeProvider>
        <AuthProvider>
          <ServiceWorker />
          {children}
        </AuthProvider>
      </ThemeProvider>
    </SWRConfig>
  );
}
