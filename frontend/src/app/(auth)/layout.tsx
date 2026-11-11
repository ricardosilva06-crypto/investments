import { Logo } from "@/components/shell/logo";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center px-6 pt-safe pb-safe">
      <div className="mb-8 flex flex-col items-center gap-3 text-center">
        <Logo className="size-16 drop-shadow-[0_8px_30px_rgba(91,108,240,0.35)]" />
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Investor Intelligence</h1>
          <p className="text-sm text-muted-foreground">Private research, on your own hardware.</p>
        </div>
      </div>
      {children}
    </main>
  );
}
