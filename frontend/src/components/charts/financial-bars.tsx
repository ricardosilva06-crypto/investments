"use client";

import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtFinancial } from "@/lib/format";

export type BarDatum = { label: string; value: number | null; derived: boolean };

/** One series over time (oldest → newest). Negative values use the negative token; derived values are hatched. */
export default function FinancialBars({ data, kind, currency, title }: { data: BarDatum[]; kind: string; currency: string; title: string }) {
  const hasNeg = data.some((d) => (d.value ?? 0) < 0);
  return (
    <figure className="w-full" aria-label={`${title} by period`}>
      <div className="h-44 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: 4 }} barCategoryGap="22%">
            <defs>
              <pattern id="derived-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <rect width="6" height="6" fill="var(--primary)" opacity="0.35" />
                <line x1="0" y1="0" x2="0" y2="6" stroke="var(--primary)" strokeWidth="2.5" />
              </pattern>
            </defs>
            <CartesianGrid vertical={false} stroke="var(--border)" strokeOpacity={0.6} />
            <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 10 }} interval="preserveStartEnd" />
            <YAxis
              width={52}
              tickLine={false}
              axisLine={false}
              tick={{ fill: "var(--muted-foreground)", fontSize: 10 }}
              tickFormatter={(v: number) => fmtFinancial(v, kind, currency)}
              tickCount={4}
            />
            {hasNeg && <ReferenceLine y={0} stroke="var(--muted-foreground)" strokeOpacity={0.6} />}
            <Tooltip
              cursor={{ fill: "var(--muted)", opacity: 0.5 }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const d = payload[0].payload as BarDatum;
                return (
                  <div className="rounded-lg border border-border bg-card px-2.5 py-1.5 text-[12px] shadow-lg">
                    <p className="text-muted-foreground">{d.label}</p>
                    <p className="num font-semibold">{fmtFinancial(d.value, kind, currency)}</p>
                    {d.derived && <p className="text-muted-foreground">Calculated</p>}
                  </div>
                );
              }}
            />
            <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false}>
              {data.map((d, i) => (
                <Cell
                  key={i}
                  fill={d.derived ? "url(#derived-hatch)" : (d.value ?? 0) < 0 ? "var(--negative)" : "var(--primary)"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
