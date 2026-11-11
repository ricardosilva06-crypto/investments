import Link from "next/link";

export default function NotFound() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-3 px-8 text-center">
      <p className="text-5xl font-bold tracking-tight">404</p>
      <p className="text-muted-foreground">This page does not exist.</p>
      <Link href="/" className="font-medium text-primary">
        Back to home
      </Link>
    </main>
  );
}
