"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { Briefcase, FileUp, Info, Plus, Trash2 } from "lucide-react";
import {
  AllocationView,
  DividendsView,
  PerformanceView,
} from "@/components/portfolio/analytics";
import { ImportSheet } from "@/components/portfolio/import-sheet";
import { Button } from "@/components/ui/button";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import {
  EmptyState,
  ErrorNote,
  PageHeader,
  SourceLine,
} from "@/components/page";
import { TickerAvatar } from "@/components/security-row";
import { api } from "@/lib/api";
import {
  fmtDate,
  fmtMoney,
  fmtPrice,
  fmtQty,
  fmtShortDate,
  signClass,
} from "@/lib/format";
import type {
  PortfolioDetail,
  PortfolioSummary,
  Position,
  Preferences,
  Transaction,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const CURRENCIES = [
  "EUR",
  "USD",
  "GBP",
  "CHF",
  "SEK",
  "NOK",
  "DKK",
  "PLN",
  "JPY",
  "CAD",
  "AUD",
  "BRL",
];
type Tab = "open" | "closed" | "tx";

function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const dec = (v: string) => v.trim().replace(",", ".");

function PositionCard({ p }: { p: Position }) {
  return (
    <div className="px-3.5 py-3">
      <div className="flex items-center gap-3">
        <TickerAvatar ticker={p.symbol} />
        <div className="min-w-0 flex-1">
          {p.security_ticker ? (
            <Link
              href={`/company?t=${encodeURIComponent(p.security_ticker)}`}
              className="font-semibold"
            >
              {p.symbol}
            </Link>
          ) : (
            <span className="font-semibold">{p.symbol}</span>
          )}
          <p className="truncate text-[12px] text-muted-foreground">
            {p.security_name ?? `${p.transactions} transactions`}
            {p.quantity !== "0" && p.valuation_note
              ? ` · ${p.valuation_note}`
              : ""}
          </p>
        </div>
        <div className="num text-right">
          {p.market_value ? (
            <>
              <p className="font-semibold">
                {fmtMoney(p.market_value, p.currency)}
              </p>
              <p
                className={cn(
                  "text-[12px] font-medium",
                  signClass(p.unrealized_pl),
                )}
              >
                {Number(p.unrealized_pl) > 0 ? "+" : ""}
                {fmtMoney(p.unrealized_pl, p.currency)}
              </p>
            </>
          ) : (
            <>
              <p className="font-semibold">
                {fmtMoney(p.cost_basis, p.currency)}
              </p>
              <p className="text-[12px] text-muted-foreground">cost basis</p>
            </>
          )}
        </div>
      </div>
      <div className="no-scrollbar -mx-3.5 mt-2 flex gap-4 overflow-x-auto px-3.5 text-[12px]">
        {[
          ...(p.market_value
            ? [
                [
                  `Close ${fmtShortDate(p.last_close_date)}`,
                  fmtPrice(p.last_close, p.currency),
                  "",
                ],
                ["Cost basis", fmtMoney(p.cost_basis, p.currency), ""],
              ]
            : []),
          ["Quantity", fmtQty(p.quantity), ""],
          [
            "Avg cost",
            p.average_cost ? fmtMoney(p.average_cost, p.currency) : "—",
            "",
          ],
          [
            "Realised P/L",
            fmtMoney(p.realized_pl, p.currency),
            signClass(p.realized_pl),
          ],
          ["Dividends", fmtMoney(p.dividends, p.currency), ""],
          ["Fees", fmtMoney(p.fees, p.currency), ""],
        ].map(([k, v, c]) => (
          <div key={k} className="shrink-0">
            <p className="text-muted-foreground">{k}</p>
            <p className={cn("num font-medium", c)}>{v}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function TxForm({
  portfolioId,
  defaultCurrency,
  onDone,
}: {
  portfolioId: number;
  defaultCurrency: string;
  onDone: () => void;
}) {
  const [f, setF] = React.useState({
    kind: "buy" as Transaction["kind"],
    symbol: "",
    trade_date: today(),
    quantity: "",
    price: "",
    fees: "0",
    currency: defaultCurrency,
    note: "",
  });
  const [error, setError] = React.useState<unknown>(null);
  const [busy, setBusy] = React.useState(false);
  const set =
    (k: keyof typeof f) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      setF({ ...f, [k]: e.target.value });
  const dividend = f.kind === "dividend";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(`/api/portfolios/${portfolioId}/transactions`, {
        method: "POST",
        // Accept European decimal commas ("12,50").
        json: {
          ...f,
          quantity: dividend ? "0" : dec(f.quantity),
          price: dec(f.price),
          fees: dec(f.fees) || "0",
        },
      });
      onDone();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3 px-4 pb-6">
      <Segmented
        value={f.kind}
        onChange={(kind) => setF({ ...f, kind })}
        options={[
          { value: "buy", label: "Buy" },
          { value: "sell", label: "Sell" },
          { value: "dividend", label: "Dividend" },
        ]}
      />
      <div className="grid grid-cols-2 gap-3">
        <Field label="Symbol" htmlFor="sym">
          <Input
            id="sym"
            value={f.symbol}
            onChange={set("symbol")}
            placeholder="AAPL, ASML.AS"
            autoCapitalize="characters"
            autoCorrect="off"
            required
            maxLength={20}
          />
        </Field>
        <Field label="Date" htmlFor="dt">
          <Input
            id="dt"
            type="date"
            value={f.trade_date}
            max={today()}
            onChange={set("trade_date")}
            required
          />
        </Field>
        {!dividend && (
          <Field label="Quantity" htmlFor="qty">
            <Input
              id="qty"
              inputMode="decimal"
              value={f.quantity}
              onChange={set("quantity")}
              placeholder="0"
              required
              pattern="[0-9]*[.,]?[0-9]*"
            />
          </Field>
        )}
        <Field
          label={dividend ? "Amount received" : "Price per share"}
          htmlFor="px"
        >
          <Input
            id="px"
            inputMode="decimal"
            value={f.price}
            onChange={set("price")}
            placeholder="0.00"
            required
            pattern="[0-9]*[.,]?[0-9]*"
          />
        </Field>
        <Field
          label={dividend ? "Withholding tax / fees" : "Fees"}
          htmlFor="fee"
        >
          <Input
            id="fee"
            inputMode="decimal"
            value={f.fees}
            onChange={set("fees")}
            pattern="[0-9]*[.,]?[0-9]*"
          />
        </Field>
        <Field label="Currency" htmlFor="ccy">
          <NativeSelect id="ccy" value={f.currency} onChange={set("currency")}>
            {CURRENCIES.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </NativeSelect>
        </Field>
      </div>
      <Field label="Note (optional)" htmlFor="nt">
        <Input id="nt" value={f.note} onChange={set("note")} maxLength={2000} />
      </Field>
      <ErrorNote error={error} />
      <Button type="submit" className="w-full" disabled={busy}>
        Save transaction
      </Button>
    </form>
  );
}

export default function PortfolioPage() {
  const router = useRouter();
  const params = useSearchParams();
  const {
    data: list,
    error: listError,
    mutate: mutateList,
  } = useSWR<PortfolioSummary[]>("/api/portfolios");
  const { data: prefs } = useSWR<Preferences>("/api/preferences");
  const pid = Number(params.get("id")) || list?.[0]?.id;
  const { data, error, mutate } = useSWR<PortfolioDetail>(
    pid ? `/api/portfolios/${pid}` : null,
  );
  const [tab, setTab] = React.useState<Tab>("open");
  const [view, setView] = React.useState<
    "holdings" | "allocation" | "performance" | "dividends"
  >("holdings");
  const [importOpen, setImportOpen] = React.useState(false);
  const [txOpen, setTxOpen] = React.useState(false);
  const [newOpen, setNewOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [opError, setOpError] = React.useState<unknown>(null);

  async function createPortfolio(e: React.FormEvent) {
    e.preventDefault();
    setOpError(null);
    try {
      const p = await api<PortfolioSummary>("/api/portfolios", {
        method: "POST",
        json: { name },
      });
      await mutateList();
      setNewOpen(false);
      setName("");
      router.replace(`/portfolio?id=${p.id}`);
    } catch (err) {
      setOpError(err);
    }
  }

  async function deleteTx(t: Transaction) {
    if (!confirm(`Delete ${t.kind} ${t.symbol} on ${fmtDate(t.trade_date)}?`))
      return;
    try {
      await api(`/api/portfolios/${pid}/transactions/${t.id}`, {
        method: "DELETE",
      });
      mutate();
    } catch (err) {
      alert((err as Error).message);
    }
  }

  async function deletePortfolio() {
    if (
      !data ||
      !confirm(
        `Delete portfolio “${data.portfolio.name}” and all its transactions?`,
      )
    )
      return;
    await api(`/api/portfolios/${data.portfolio.id}`, { method: "DELETE" });
    await mutateList();
    router.replace("/portfolio");
  }

  return (
    <div>
      <PageHeader
        title="Portfolio"
        subtitle={
          data
            ? `${data.open_positions.length} open position${data.open_positions.length === 1 ? "" : "s"}`
            : undefined
        }
        action={
          data && (
            <Button size="sm" onClick={() => setTxOpen(true)}>
              <Plus /> Transaction
            </Button>
          )
        }
      />
      <ErrorNote error={listError || error} />

      {list && (
        <div className="no-scrollbar -mx-4 mb-3 flex gap-2 overflow-x-auto px-4 pb-1">
          {list.map((p) => (
            <button
              key={p.id}
              onClick={() =>
                router.replace(`/portfolio?id=${p.id}`, { scroll: false })
              }
              className={cn(
                "shrink-0 rounded-full border border-border px-3.5 py-1.5 text-[13px] font-medium",
                p.id === pid
                  ? "border-primary bg-primary text-primary-foreground"
                  : "bg-card text-muted-foreground",
              )}
            >
              {p.name}
            </button>
          ))}
          <button
            onClick={() => setNewOpen(true)}
            className="flex shrink-0 items-center gap-1 rounded-full border border-dashed border-border px-3 py-1.5 text-[13px] text-muted-foreground"
          >
            <Plus className="size-3.5" /> New
          </button>
        </div>
      )}

      {!list && !listError && <Skeleton className="h-40" />}
      {list && list.length === 0 && (
        <EmptyState icon={Briefcase} title="No portfolio yet">
          <p>
            Record your buys, sells and dividends. Positions, cost basis and
            realised gains are calculated from your own entries.
          </p>
          <Button size="sm" className="mt-3" onClick={() => setNewOpen(true)}>
            <Plus /> Create portfolio
          </Button>
        </EmptyState>
      )}

      {data && (
        <>
          <div className="no-scrollbar -mx-4 flex snap-x gap-2 overflow-x-auto px-4">
            {data.totals_by_currency.length === 0 ? (
              <div className="w-full rounded-2xl border border-border/60 bg-card p-4 text-[13px] text-muted-foreground">
                No transactions yet.
              </div>
            ) : (
              data.totals_by_currency.map((t) => (
                <div
                  key={t.currency}
                  className={cn(
                    "snap-start rounded-2xl bg-gradient-to-br from-primary/20 via-card to-card p-4 ring-1 ring-border/60",
                    data.totals_by_currency.length > 1
                      ? "min-w-[82%]"
                      : "w-full",
                  )}
                >
                  <div className="flex items-center justify-between">
                    <p className="text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
                      {t.market_value ? "Market value" : "Open cost basis"}
                    </p>
                    <Badge variant="muted">{t.currency}</Badge>
                  </div>
                  <p className="num mt-1 text-[28px] font-bold tracking-tight">
                    {fmtMoney(t.market_value ?? t.cost_basis, t.currency)}
                  </p>
                  {t.market_value ? (
                    <p className="text-[12px] text-muted-foreground">
                      At closes up to {fmtDate(t.oldest_price_date)} · cost{" "}
                      {fmtMoney(t.cost_basis, t.currency)} ·{" "}
                      <span
                        className={cn(
                          "font-semibold",
                          signClass(t.unrealized_pl),
                        )}
                      >
                        unrealised {Number(t.unrealized_pl) > 0 ? "+" : ""}
                        {fmtMoney(t.unrealized_pl, t.currency)}
                      </span>
                    </p>
                  ) : (
                    t.open_positions > 0 && (
                      <p className="text-[12px] text-muted-foreground">
                        Prices stored for {t.priced_positions} of{" "}
                        {t.open_positions} open positions; total market value
                        needs all of them.
                      </p>
                    )
                  )}
                  <div className="mt-2 grid grid-cols-2 gap-2 text-[13px]">
                    <div>
                      <p className="text-muted-foreground">Realised P/L</p>
                      <p
                        className={cn(
                          "num font-semibold",
                          signClass(t.realized_pl),
                        )}
                      >
                        {fmtMoney(t.realized_pl, t.currency)}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Dividends (net)</p>
                      <p className="num font-semibold">
                        {fmtMoney(t.dividends, t.currency)}
                      </p>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
          <div className="mt-2 flex gap-2 rounded-xl bg-elevated px-3 py-2 text-[12px] text-muted-foreground">
            <Info className="mt-0.5 size-3.5 shrink-0" />
            <span>{data.market_value_note}</span>
          </div>

          <Segmented
            className="mt-4"
            value={view}
            onChange={setView}
            options={[
              { value: "holdings", label: "Holdings" },
              { value: "allocation", label: "Allocation" },
              { value: "performance", label: "Value" },
              { value: "dividends", label: "Dividends" },
            ]}
          />
          {view === "allocation" && (
            <div className="mt-3">
              <AllocationView
                pid={data.portfolio.id}
                base={prefs?.base_currency}
              />
            </div>
          )}
          {view === "performance" && (
            <div className="mt-3">
              <PerformanceView pid={data.portfolio.id} />
            </div>
          )}
          {view === "dividends" && (
            <div className="mt-3">
              <DividendsView pid={data.portfolio.id} />
            </div>
          )}
          {view === "holdings" && (
            <>
              <Segmented
                className="mt-3"
                value={tab}
                onChange={setTab}
                options={[
                  {
                    value: "open",
                    label: `Open (${data.open_positions.length})`,
                  },
                  {
                    value: "closed",
                    label: `Closed (${data.closed_positions.length})`,
                  },
                  { value: "tx", label: "History" },
                ]}
              />

              <div className="mt-3 overflow-hidden rounded-2xl border border-border/60 bg-card">
                {tab !== "tx" ? (
                  (tab === "open" ? data.open_positions : data.closed_positions)
                    .length ? (
                    <ul className="divide-y divide-border/60">
                      {(tab === "open"
                        ? data.open_positions
                        : data.closed_positions
                      ).map((p) => (
                        <li key={`${p.symbol}-${p.currency}`}>
                          <PositionCard p={p} />
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="p-4 text-center text-[13px] text-muted-foreground">
                      No {tab} positions.
                    </p>
                  )
                ) : data.transactions.length ? (
                  <ul className="divide-y divide-border/60">
                    {data.transactions.map((t) => (
                      <li
                        key={t.id}
                        className="flex items-center gap-3 px-3.5 py-3"
                      >
                        <Badge
                          variant={
                            t.kind === "buy"
                              ? "default"
                              : t.kind === "sell"
                                ? "warning"
                                : "positive"
                          }
                          className="w-16 justify-center uppercase"
                        >
                          {t.kind}
                        </Badge>
                        <div className="min-w-0 flex-1">
                          <p className="font-semibold">{t.symbol}</p>
                          <p className="truncate text-[12px] text-muted-foreground">
                            {fmtDate(t.trade_date)}
                            {t.note ? ` · ${t.note}` : ""}
                          </p>
                        </div>
                        <div className="num text-right text-[13px]">
                          {t.kind === "dividend" ? (
                            <p className="font-medium">
                              {fmtMoney(t.price, t.currency)}
                            </p>
                          ) : (
                            <>
                              <p className="font-medium">
                                {fmtQty(t.quantity)} ×{" "}
                                {fmtMoney(t.price, t.currency)}
                              </p>
                              {Number(t.fees) > 0 && (
                                <p className="text-muted-foreground">
                                  fees {fmtMoney(t.fees, t.currency)}
                                </p>
                              )}
                            </>
                          )}
                        </div>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label="Delete transaction"
                          onClick={() => deleteTx(t)}
                        >
                          <Trash2 className="text-muted-foreground" />
                        </Button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="p-4 text-center text-[13px] text-muted-foreground">
                    No transactions recorded.
                  </p>
                )}
              </div>
              <SourceLine>
                Cost basis and realised P/L are calculated from your
                transactions (average-cost method). Market values use stored
                end-of-day closes.
              </SourceLine>
            </>
          )}
          <div className="mt-4 flex justify-between">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setImportOpen(true)}
            >
              <FileUp /> Import CSV
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-negative"
              onClick={deletePortfolio}
            >
              <Trash2 /> Delete portfolio
            </Button>
          </div>
          <ImportSheet
            pid={data.portfolio.id}
            open={importOpen}
            onOpenChange={setImportOpen}
            onDone={() => mutate()}
          />

          <Sheet open={txOpen} onOpenChange={setTxOpen}>
            <SheetContent
              title="Record transaction"
              description={data.portfolio.name}
            >
              <TxForm
                portfolioId={data.portfolio.id}
                defaultCurrency={prefs?.base_currency ?? "EUR"}
                onDone={() => {
                  setTxOpen(false);
                  mutate();
                }}
              />
            </SheetContent>
          </Sheet>
        </>
      )}

      <Sheet open={newOpen} onOpenChange={setNewOpen}>
        <SheetContent title="New portfolio">
          <form onSubmit={createPortfolio} className="space-y-3 px-4 pb-6">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Long-term, Dividend"
              required
              maxLength={80}
              autoFocus
            />
            <ErrorNote error={opError} />
            <Button type="submit" className="w-full">
              Create
            </Button>
          </form>
        </SheetContent>
      </Sheet>
    </div>
  );
}
