"use client";

import { Suspense } from "react";
import { AppShell } from "@/components/shell/app-shell";
import { Skeleton } from "@/components/ui/skeleton";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AppShell>
      <Suspense fallback={<Skeleton className="h-40" />}>{children}</Suspense>
    </AppShell>
  );
}
