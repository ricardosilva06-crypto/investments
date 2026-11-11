"use client";

import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtFinancial, fmtShortDate } from "@/lib/format";

export default function ValueHistory({ points, currency }: { points: { date: string; value: number | null; cost: number }[]; currency: string }) {
  return (
    <div className="h-52 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 4 }}>
          <CartesianGrid vertical={false} stroke="var(--border)" strokeOpacity={0.6} />
          <XAxis dataKey="date" tickFormatter={fmtShortDate} tickLine={false} axisLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 10 }} minTickGap={28} />
          <YAxis width={56} tickLine={false} axisLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 10 }} tickFormatter={(v: number) => fmtFinancial(v, "money", currency)} domain={["auto", "auto"]} tickCount={4} />
          <Tooltip
            content={({ active, payload, label }) =>
              active && payload?.length ? (
                <div className="rounded-lg border border-border bg-card px-2.5 py-1.5 text-[12px] shadow-lg">
                  <p className="text-muted-foreground">{fmtShortDate(String(label))}</p>
                  {payload.map((p) => (
                    <p key={String(p.dataKey)} className="num">
                      {p.dataKey === "value" ? "Market value" : "Cost basis"}: <span className="font-semibold">{p.value === null ? "—" : fmtFinancial(p.value as number, "money", currency)}</span>
                    </p>
                  ))}
                </div>
              ) : null
            }
          />
          <Legend iconType="plainline" formatter={(v) => (v === "value" ? "Market value" : "Cost basis")} wrapperStyle={{ fontSize: 12 }} />
          <Line type="monotone" dataKey="value" stroke="var(--series-1)" strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
          <Line type="stepAfter" dataKey="cost" stroke="var(--muted-foreground)" strokeWidth={1.5} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
