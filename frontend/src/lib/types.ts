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
  is_shared: boolean;
  is_mine: boolean;
  author: string | null;
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
  watch_items: { watchlist_id: number; watchlist_name: string; security: Security; note: string; quote: Quote | null }[];
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

export type FinCell = {
  value: string;
  concept: string;
  unit: string;
  accession: string;
  form: string;
  filed: string | null;
  derived: boolean;
  formula: string;
  url?: string;
};

export type FinRow = { key: string; label: string; kind: string; indent: number; values: (FinCell | null)[] };

export type Statement = {
  statement: "income" | "balance" | "cashflow" | "metrics";
  period: "annual" | "quarterly";
  currency: string;
  periods: { start: string | null; end: string; label: string }[];
  rows: FinRow[];
  source: { name: string; url: string | null; last_success_at: string | null };
};

export type KeyFigure = {
  key: string;
  label: string;
  kind: string;
  value: string;
  period_end: string;
  derived: boolean;
  formula: string;
  concept: string;
  form: string;
  filed: string | null;
};

export type CompanyProfile = {
  cik: number;
  name: string;
  entity_type: string;
  sic: string;
  sic_description: string;
  category: string;
  fiscal_year_end: string;
  state_of_incorporation: string;
  business_address: string;
  phone: string;
  website: string;
  investor_website: string;
  tickers: string[];
  exchanges: string[];
  former_names: { name: string; from?: string; to?: string }[];
};

export type Company = {
  security: Security;
  profile: CompanyProfile | null;
  freshness: { source: string; status: string; message: string; last_success_at: string | null }[];
  errors: Record<string, string>;
  quote: Quote | null;
  key_figures: KeyFigure[];
  currency: string;
  has_financials: boolean;
};

export type FilingRow = { accession: string; form: string; filing_date: string; report_date: string | null; description: string; url: string };

export type PriceBar = { date: string; open: string | null; high: string | null; low: string | null; close: string; adj_close: string | null; volume: number | null };
export type Prices = {
  ticker: string;
  bars: PriceBar[];
  sources: string[];
  currency: string | null;
  last_date: string | null;
  provider_configured: boolean;
  error: string | null;
  note: string;
};

export type FxRate = { currency: string; date: string; value: string; prev_value: string | null; change_pct: string | null };
export type Fx = {
  base: string;
  rates: FxRate[];
  source: string;
  source_url: string;
  status: string;
  message: string;
  last_success_at: string | null;
  note: string;
};

export type AIModel = { name: string; size_bytes: number | null; family: string; parameter_size: string; quantization: string; embedding: boolean };
export type AIStatus = {
  available: boolean;
  message: string;
  url: string;
  models: AIModel[];
  chat_model: string | null;
  embed_model: string | null;
  chosen_chat_model: string;
  chosen_embed_model: string;
  temperature: string;
  num_ctx: number;
  tasks: Record<string, string>;
};
export type DocItem = {
  id: number;
  title: string;
  filename: string;
  size_bytes: number;
  pages: number;
  chars: number;
  status: "extracted" | "indexing" | "ready" | "keyword_only" | "error";
  message: string;
  embed_model: string;
  created_at: string;
  ticker: string | null;
};
export type AISource = { id: string; kind: string; label: string; url: string | null; detail: string };
export type Verification = { checked?: number; unmatched_verified?: string[]; unmatched_other?: string[]; has_structure?: boolean };
export type ChatMsg = {
  id: number;
  role: "user" | "assistant";
  content: string;
  task: string;
  tickers: string[];
  document_ids: number[];
  model: string;
  sources: AISource[];
  verification: Verification;
  status: string;
  created_at: string;
};
export type ConversationSummary = { id: number; title: string; created_at: string; updated_at: string };
export type ConversationDetail = ConversationSummary & { messages: ChatMsg[] };

export type ScreenerMeta = Record<string, { label: string; kind: string }>;
export type ScreenerItem = { cik: number; ticker: string | null; name: string; exchange: string | null; period_end: string | null; values: Record<string, string | null> };
export type ScreenerResult = {
  years: number[];
  year: number | null;
  metrics: ScreenerMeta;
  source: string;
  last_success_at: string | null;
  status: string;
  message: string;
  total: number;
  coverage: number;
  items: ScreenerItem[];
};

export type DcfField = { value: string | number | null; label: string; kind: "reported" | "calculated" | "assumption" | "missing"; source: string };
export type DcfInputs = {
  ticker: string;
  name: string;
  currency: string;
  errors: Record<string, string>;
  fields: Record<string, DcfField>;
  history: { end: string; fcf: string; cfo: string; capex: string }[];
  price: { close: string; date: string; source: string } | null;
};
export type DcfResult = {
  result: {
    projection: { year: number; growth: string; fcf: string; discount_factor: string; pv: string }[];
    pv_fcf: string;
    terminal_value: string;
    pv_terminal: string;
    terminal_share: string | null;
    enterprise_value: string;
    equity_value: string;
    per_share: string;
    upside: string | null;
    implied_multiple: string | null;
    warning?: string;
  };
  sensitivity: { discount_rates: string[]; terminal_growths: string[]; per_share: (string | null)[][] };
};
export type SavedValuation = { id: number; ticker: string; name: string; inputs: Record<string, string | number>; summary: Record<string, string | null>; created_at: string };

export type CompareCompany = {
  ticker: string;
  name: string;
  currency: string | null;
  fiscal_year_end: string | null;
  fields: Record<string, FinCell | null>;
  quote: { close: string; date: string; source: string; currency: string } | null;
  pe: string | null;
  history: { end: string; revenue: string | null; net_income: string | null; fcf: string | null }[];
  errors: Record<string, string>;
};
export type CompareResult = { fields: { key: string; label: string; kind: string }[]; companies: CompareCompany[] };

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

export type NewsEntry = { type: "news" | "filing"; title: string; link: string; summary: string; source: string; ticker: string | null; date: string; date_is_published: boolean };
export type FeedItem = { id: number; url: string; title: string; ticker: string | null; status: string; message: string; last_fetch_at: string | null };
export type AlertItem = {
  id: number;
  ticker: string;
  kind: "price_above" | "price_below" | "daily_move" | "filing";
  threshold: string | null;
  forms: string;
  active: boolean;
  repeat: boolean;
  note: string;
  last_checked_at: string | null;
  last_triggered_at: string | null;
  created_at: string;
};
