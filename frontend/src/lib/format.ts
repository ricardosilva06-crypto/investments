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

/** Compact financial-statement value, by row kind. */
export function fmtFinancial(v: string | number | null | undefined, kind: string, currency: string) {
  const n = toNumber(v);
  if (n === null) return "—";
  switch (kind) {
    case "percent":
      return `${(n * 100).toFixed(1)}%`;
    case "ratio":
      return `${n.toFixed(2)}×`;
    case "per_share":
      return fmtMoney(n, currency);
    case "shares":
      return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 2 }).format(n);
    default:
      try {
        return new Intl.NumberFormat(undefined, {
          style: "currency",
          currency,
          notation: Math.abs(n) >= 10_000 ? "compact" : "standard",
          maximumFractionDigits: Math.abs(n) >= 10_000 ? 2 : 0,
        }).format(n);
      } catch {
        return n.toLocaleString();
      }
  }
}

export function fmtPct(v: string | number | null | undefined, digits = 2) {
  const n = toNumber(v);
  if (n === null) return "—";
  return `${n > 0 ? "+" : ""}${(n * 100).toFixed(digits)}%`;
}

export function fmtPrice(v: string | number | null | undefined, currency: string) {
  const n = toNumber(v);
  if (n === null) return "—";
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency, minimumFractionDigits: 2, maximumFractionDigits: n < 1 ? 4 : 2 }).format(n);
  } catch {
    return n.toFixed(2);
  }
}

export function fmtShortDate(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  return new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" }).format(d);
}
