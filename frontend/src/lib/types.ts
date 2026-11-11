export type User = { id: number; username: string; display_name: string; role: "admin" | "member"; created_at: string };

export type Security = {
  id: number;
  ticker: string;
  name: string;
  cik: number | null;
  exchange: string | null;
  source: string;
  is_listed: boolean;
  updated_at: string;
};

export type SourceStatus = {
  source: string;
  source_url: string;
  status: "never" | "ok" | "error";
  message: string;
  record_count: number;
  last_attempt_at: string | null;
  last_success_at: string | null;
};

export type WatchItem = { id: number; note: string; added_at: string; security: Security };
export type Watchlist = { id: number; name: string; created_at: string; items: WatchItem[] };

export type Note = {
  id: number;
  title: string;
  body: string;
  created_at: string;
  updated_at: string;
  security: Security | null;
};

export type Notification = {
  id: number;
  kind: string;
  title: string;
  body: string;
  link: string;
  created_at: string;
  read_at: string | null;
};

export type Preferences = { theme: "dark" | "light" | "system"; base_currency: string; compact_numbers: boolean };

export type Dashboard = {
  display_name: string;
  watchlist_count: number;
  watched_securities: number;
  watch_items: { watchlist_id: number; watchlist_name: string; security: Security; note: string }[];
  recent_notes: { id: number; title: string; updated_at: string }[];
  note_count: number;
  portfolios: { id: number; name: string; open_positions: number; cost_basis_by_currency: Record<string, string>; error: string | null }[];
  unread_notifications: number;
  securities_available: number;
  data_sources: SourceStatus[];
};

export type SystemStatus = {
  server_time: string;
  data_sources: SourceStatus[];
  ai: { available: boolean; url: string; models: string[]; message: string };
};

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
  security_id: number | null;
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
};
export type PortfolioDetail = {
  portfolio: PortfolioSummary;
  open_positions: Position[];
  closed_positions: Position[];
  totals_by_currency: { currency: string; cost_basis: string; realized_pl: string; dividends: string }[];
  transactions: Transaction[];
  market_value_note: string;
};
