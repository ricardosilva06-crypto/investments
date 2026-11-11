"use client";

import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtShortDate } from "@/lib/format";

export default function LineMini({ points, digits = 4 }: { points: { date: string; value: number }[]; digits?: number }) {
  return (
    <div className="h-40 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <XAxis dataKey="date" tickFormatter={fmtShortDate} tickLine={false} axisLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 10 }} minTickGap={24} />
          <YAxis domain={["auto", "auto"]} width={52} tickLine={false} axisLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 10 }} tickFormatter={(v: number) => v.toFixed(digits)} tickCount={4} />
          <Tooltip
            cursor={{ stroke: "var(--muted-foreground)", strokeDasharray: "3 3" }}
            content={({ active, payload }) =>
              active && payload?.length ? (
                <div className="rounded-lg border border-border bg-card px-2.5 py-1.5 text-[12px] shadow-lg">
                  <p className="text-muted-foreground">{fmtShortDate(String(payload[0].payload.date))}</p>
                  <p className="num font-semibold">{Number(payload[0].value).toFixed(digits)}</p>
                </div>
              ) : null
            }
          />
          <Line type="linear" dataKey="value" stroke="var(--primary)" strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--card)" }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
