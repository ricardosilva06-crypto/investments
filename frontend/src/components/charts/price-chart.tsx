"use client";

import * as React from "react";
import { AreaSeries, CandlestickSeries, ColorType, createChart, type IChartApi, type UTCTimestamp } from "lightweight-charts";
import type { PriceBar } from "@/lib/types";

function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Resolve any CSS colour (incl. oklch) to rgba() by painting one canvas pixel. */
function toRgb(color: string, alpha = 1) {
  const c = document.createElement("canvas");
  c.width = c.height = 1;
  const ctx = c.getContext("2d", { willReadFrequently: true });
  if (!ctx) return color;
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
  return `rgba(${r}, ${g}, ${b}, ${((a / 255) * alpha).toFixed(3)})`;
}

function toTime(d: string) {
  return (Date.parse(`${d}T00:00:00Z`) / 1000) as UTCTimestamp;
}

/**
 * End-of-day price chart (TradingView Lightweight Charts, Apache-2.0).
 * The library's attribution logo is kept on, as its licence requires.
 */
export default function PriceChart({ bars, mode, dark }: { bars: PriceBar[]; mode: "area" | "candles"; dark: boolean }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const chartRef = React.useRef<IChartApi | null>(null);

  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const fg = toRgb(cssVar("--muted-foreground"));
    const grid = toRgb(cssVar("--border"), 0.5);
    const primary = toRgb(cssVar("--primary"));
    const pos = toRgb(cssVar("--positive"));
    const neg = toRgb(cssVar("--negative"));

    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: fg,
        fontFamily: getComputedStyle(document.body).fontFamily,
        fontSize: 11,
        attributionLogo: true,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: grid } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, fixLeftEdge: true, fixRightEdge: true },
      crosshair: { horzLine: { labelBackgroundColor: primary }, vertLine: { labelBackgroundColor: primary } },
      handleScale: { axisPressedMouseMove: false },
      handleScroll: { vertTouchDrag: false },
    });
    chartRef.current = chart;

    const hasOhlc = bars.every((b) => b.open && b.high && b.low);
    if (mode === "candles" && hasOhlc) {
      const s = chart.addSeries(CandlestickSeries, {
        upColor: pos,
        downColor: neg,
        borderVisible: false,
        wickUpColor: pos,
        wickDownColor: neg,
      });
      s.setData(bars.map((b) => ({ time: toTime(b.date), open: +b.open!, high: +b.high!, low: +b.low!, close: +b.close })));
    } else {
      const s = chart.addSeries(AreaSeries, {
        lineColor: primary,
        lineWidth: 2,
        topColor: toRgb(cssVar("--primary"), 0.28),
        bottomColor: toRgb(cssVar("--primary"), 0.02),
        priceLineVisible: false,
      });
      s.setData(bars.map((b) => ({ time: toTime(b.date), value: +b.close })));
    }
    chart.timeScale().fitContent();
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [bars, mode, dark]);

  return <div ref={ref} className="h-56 w-full" role="img" aria-label="End-of-day price chart" />;
}
