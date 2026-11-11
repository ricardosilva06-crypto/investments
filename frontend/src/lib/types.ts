export type Security = { ticker: string; name: string; exchange: string | null };

export type Quote = {
  close: string;
  date: string;
  prev_close: string | null;
  prev_date: string | null;
  change: string | null;
  change_pct: string | null;
  source: string;
  currency: string;
};

export type WatchItem = { id: number; note: string; added_at: string; security: Security; quote: Quote | null };
export type Watchlist = { id: number; name: string; created_at: string; items: WatchItem[] };

export type Note = {
  id: number;
  title: string;
  body: string;
  created_at: string;
  updated_at: string;
  security: Security | null;
};

export type Preferences = { theme: "dark" | "light" | "system"; base_currency: string; compact_numbers: boolean; display_name: string };

export type Dashboard = {
  watchlist_count: number;
  watched_securities: number;
  watch_items: { watchlist_id: number; watchlist_name: string; security: Security; note: string; quote: Quote | null }[];
  recent_notes: { id: number; title: string; updated_at: string }[];
  note_count: number;
  portfolios: { id: number; name: string; open_positions: number; cost_basis_by_currency: Record<string, string>; error: string | null }[];
  last_backup_at: string | null;
  has_data: boolean;
  backup_due: boolean;
};

export type SecurityListItem = Security & { quote: Quote | null; bars: number };
export type PriceBar = { ticker: string; date: string; open: string | null; high: string | null; low: string | null; close: string; adj_close: string | null; volume: number | null; source: string; currency: string };
export type Prices = { ticker: string; bars: PriceBar[]; sources: string[]; currency: string | null; last_date: string | null; note: string };
export type FxRate = { currency: string; value: string; date: string; source: string };

export type SearchHit = { type: "security" | "note" | "watchlist" | "holding"; title: string; subtitle: string; href: string };

export type PortfolioSummary = { id: number; name: string; created_at: string };
export type Transaction = {
  id: number;
  symbol: string;
  kind: "buy" | "sell" | "dividend";
  trade_date: string;
  quantity: string;
  price: string;
  fees: string;
  currency: string;
  note: string;
  created_at: string;
};
export type Position = {
  symbol: string;
  currency: string;
  quantity: string;
  average_cost: string | null;
  cost_basis: string;
  realized_pl: string;
  dividends: string;
  fees: string;
  transactions: number;
  first_trade: string | null;
  security_ticker: string | null;
  security_name: string | null;
  last_close: string | null;
  last_close_date: string | null;
  price_source: string | null;
  market_value: string | null;
  unrealized_pl: string | null;
  valuation_note: string | null;
};
export type PortfolioDetail = {
  portfolio: PortfolioSummary;
  open_positions: Position[];
  closed_positions: Position[];
  totals_by_currency: {
    currency: string;
    cost_basis: string;
    realized_pl: string;
    dividends: string;
    market_value: string | null;
    unrealized_pl: string | null;
    priced_positions: number;
    open_positions: number;
    oldest_price_date: string | null;
  }[];
  transactions: Transaction[];
  market_value_note: string;
};

export type Analytics = {
  allocation: {
    items: { symbol: string; currency: string; value: string; basis: "market" | "cost"; price_date: string | null; weight_in_currency: string | null; value_base?: string; weight_total?: string | null }[];
    totals: Record<string, string>;
    base: null | { currency: string; error?: string; total?: string; rate_date?: string; includes_cost_basis?: boolean; note?: string };
  };
  history: Record<string, { date: string; value: string | null; cost: string }[]>;
  dividends: {
    by_year: Record<string, { year: number; amount: string }[]>;
    ttm_by_currency: Record<string, string>;
    last_12_months: Record<string, { month: string; amount: string }[]>;
    by_symbol: { symbol: string; currency: string; total: string; ttm: string; payments: number; last_date: string; cost_basis: string | null; yield_on_cost: string | null }[];
    note: string;
  };
  history_note: string;
  returns: Record<
    string,
    {
      start: string;
      end: string;
      days: number;
      twr_total: string | null;
      twr_annualised: string | null;
      twr_ytd: string | null;
      twr_1y: string | null;
      mwr_annualised: string | null;
      gaps: number;
      series: { date: string; twr: string }[];
    }
  >;
  returns_note: string;
};

