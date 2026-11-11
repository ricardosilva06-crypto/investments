export function toNumber(v: string | number | null | undefined): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

export function fmtMoney(v: string | number | null | undefined, currency: string, compact = false) {
  const n = toNumber(v);
  if (n === null) return "—";
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      notation: compact && Math.abs(n) >= 100_000 ? "compact" : "standard",
      maximumFractionDigits: compact && Math.abs(n) >= 100_000 ? 2 : 2,
    }).format(n);
  } catch {
    return `${n.toFixed(2)} ${currency}`;
  }
}

export function fmtQty(v: string | number | null | undefined) {
  const n = toNumber(v);
  if (n === null) return "—";
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 6 }).format(n);
}

export function fmtInt(v: number | null | undefined) {
  return v === null || v === undefined ? "—" : new Intl.NumberFormat().format(v);
}

export function fmtDate(iso: string | null | undefined, withTime = false) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  }).format(d);
}

export function fmtRelative(iso: string | null | undefined) {
  if (!iso) return "never";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} d ago`;
  return fmtDate(iso);
}

export function signClass(v: string | number | null | undefined) {
  const n = toNumber(v);
  if (n === null || n === 0) return "text-foreground";
  return n > 0 ? "text-positive" : "text-negative";
}
