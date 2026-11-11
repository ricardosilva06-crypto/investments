"use client";

import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtPct, fmtShortDate } from "@/lib/format";

/** Cumulative time-weighted return (single series, so no legend: the card title names it). */
export default function TwrChart({ points }: { points: { date: string; twr: number }[] }) {
  return (
    <div className="h-52 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 4 }}>
          <CartesianGrid vertical={false} stroke="var(--border)" strokeOpacity={0.6} />
          <XAxis dataKey="date" tickFormatter={fmtShortDate} tickLine={false} axisLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 10 }} minTickGap={28} />
          <YAxis width={48} tickLine={false} axisLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 10 }} tickFormatter={(v: number) => fmtPct(v, 0)} domain={["auto", "auto"]} tickCount={5} />
          <ReferenceLine y={0} stroke="var(--muted-foreground)" strokeOpacity={0.6} />
          <Tooltip
            cursor={{ stroke: "var(--muted-foreground)", strokeDasharray: "3 3" }}
            content={({ active, payload, label }) =>
              active && payload?.length ? (
                <div className="rounded-lg border border-border bg-card px-2.5 py-1.5 text-[12px] shadow-lg">
                  <p className="text-muted-foreground">{fmtShortDate(String(label))}</p>
                  <p className="num font-semibold">TWR {fmtPct(payload[0].value as number)}</p>
                </div>
              ) : null
            }
          />
          <Line type="monotone" dataKey="twr" stroke="var(--series-1)" strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--card)" }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
