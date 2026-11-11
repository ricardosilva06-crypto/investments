"use client";

import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtFinancial } from "@/lib/format";

const COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];
const DASH = ["0", "6 3", "2 3"]; // secondary encoding so identity is not colour-only

/** Multi-company history by fiscal year. One currency only (caller guarantees). */
export default function CompareLines({ data, series, currency }: { data: Record<string, string | number | null>[]; series: string[]; currency: string }) {
  return (
    <div className="h-56 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 4 }}>
          <CartesianGrid vertical={false} stroke="var(--border)" strokeOpacity={0.6} />
          <XAxis dataKey="year" tickLine={false} axisLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 10 }} />
          <YAxis width={56} tickLine={false} axisLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 10 }} tickFormatter={(v: number) => fmtFinancial(v, "money", currency)} tickCount={4} />
          <Tooltip
            content={({ active, payload, label }) =>
              active && payload?.length ? (
                <div className="rounded-lg border border-border bg-card px-2.5 py-1.5 text-[12px] shadow-lg">
                  <p className="text-muted-foreground">{label}</p>
                  {payload.map((p) => (
                    <p key={String(p.dataKey)} className="num flex items-center gap-1.5">
                      <span className="inline-block size-2 rounded-full" style={{ background: p.color }} />
                      {String(p.dataKey)}: <span className="font-semibold">{fmtFinancial(p.value as number, "money", currency)}</span>
                    </p>
                  ))}
                </div>
              ) : null
            }
          />
          <Legend iconType="plainline" wrapperStyle={{ fontSize: 12, color: "var(--foreground)" }} />
          {series.map((s, i) => (
            <Line key={s} type="monotone" dataKey={s} stroke={COLORS[i]} strokeWidth={2} strokeDasharray={DASH[i]} dot={{ r: 4, strokeWidth: 2, stroke: "var(--card)", fill: COLORS[i] }} connectNulls={false} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
