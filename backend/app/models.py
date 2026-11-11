"""Database tables.

Every user-owned table carries a ``user_id`` (directly or through its parent)
and every query in the routers filters on the authenticated user's id.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, DecimalString, UTCDateTime, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="member")  # admin | member
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    invited_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Only a SHA-256 hash of the session token is stored.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_agent: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)

    user: Mapped[User] = relationship()


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    code_hint: Mapped[str] = mapped_column(String(8))  # first chars, for admin display only
    label: Mapped[str] = mapped_column(String(80), default="")
    role: Mapped[str] = mapped_column(String(16), default="member")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Security(Base):
    """A listed security from an official reference list (SEC EDGAR for now)."""

    __tablename__ = "securities"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    cik: Mapped[int | None] = mapped_column(Integer, index=True)
    # Legal Entity Identifier, for companies whose fundamentals come from ESEF reports (EU issuers).
    lei: Mapped[str | None] = mapped_column(String(20), index=True)
    exchange: Mapped[str | None] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(64))
    # False when the ticker disappeared from the latest source file.
    is_listed: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class DataSync(Base):
    """Provenance and freshness of every external data source."""

    __tablename__ = "data_syncs"

    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_url: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="never")  # never | ok | error
    message: Mapped[str] = mapped_column(Text, default="")
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    items: Mapped[list["WatchlistItem"]] = relationship(
        back_populates="watchlist", cascade="all, delete-orphan", order_by="WatchlistItem.added_at"
    )


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "security_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"), index=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id", ondelete="CASCADE"))
    note: Mapped[str] = mapped_column(Text, default="")
    added_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    watchlist: Mapped[Watchlist] = relationship(back_populates="items")
    security: Mapped[Security] = relationship()


class Note(Base):
    """Private investment notes / theses. Visible only to their owner."""

    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    security_id: Mapped[int | None] = mapped_column(ForeignKey("securities.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text, default="")
    # Optional shared research: visible read-only to other members only when the owner opts in.
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    security: Mapped[Security | None] = relationship()


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )


class Transaction(Base):
    """A transaction entered by the user. Symbols are free-form so non-US
    securities (e.g. Euronext listings) can be recorded too."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"), index=True)
    security_id: Mapped[int | None] = mapped_column(ForeignKey("securities.id", ondelete="SET NULL"))
    symbol: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(16))  # buy | sell | dividend
    trade_date: Mapped[date] = mapped_column(Date)
    quantity: Mapped[Decimal] = mapped_column(DecimalString, default=Decimal(0))
    price: Mapped[Decimal] = mapped_column(DecimalString, default=Decimal(0))  # per share; dividend = total amount
    fees: Mapped[Decimal] = mapped_column(DecimalString, default=Decimal(0))
    currency: Mapped[str] = mapped_column(String(3))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    portfolio: Mapped[Portfolio] = relationship(back_populates="transactions")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    theme: Mapped[str] = mapped_column(String(8), default="dark")  # dark | light | system
    base_currency: Mapped[str] = mapped_column(String(3), default="EUR")
    compact_numbers: Mapped[bool] = mapped_column(Boolean, default=True)


# ----------------------------------------------------------------- Phase 2
class FetchState(Base):
    """Freshness of per-entity downloads, e.g. ("sec_companyfacts", "320193")."""

    __tablename__ = "fetch_states"
    __table_args__ = (UniqueConstraint("source", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(48))
    key: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="never")  # ok | error | not_found
    message: Mapped[str] = mapped_column(Text, default="")
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class CompanyProfile(Base):
    """From SEC EDGAR submissions JSON (data.sec.gov/submissions/CIK##########.json)."""

    __tablename__ = "company_profiles"

    cik: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    entity_type: Mapped[str] = mapped_column(String(64), default="")
    sic: Mapped[str] = mapped_column(String(8), default="")
    sic_description: Mapped[str] = mapped_column(String(255), default="")
    category: Mapped[str] = mapped_column(String(128), default="")
    fiscal_year_end: Mapped[str] = mapped_column(String(4), default="")  # MMDD
    state_of_incorporation: Mapped[str] = mapped_column(String(64), default="")
    business_address: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    website: Mapped[str] = mapped_column(String(255), default="")
    investor_website: Mapped[str] = mapped_column(String(255), default="")
    tickers: Mapped[str] = mapped_column(String(255), default="")  # comma separated
    exchanges: Mapped[str] = mapped_column(String(255), default="")
    former_names: Mapped[str] = mapped_column(Text, default="")  # JSON list
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Filing(Base):
    __tablename__ = "filings"
    __table_args__ = (UniqueConstraint("cik", "accession"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cik: Mapped[int] = mapped_column(Integer, index=True)
    accession: Mapped[str] = mapped_column(String(25))
    form: Mapped[str] = mapped_column(String(20), index=True)
    filing_date: Mapped[date] = mapped_column(Date, index=True)
    report_date: Mapped[date | None] = mapped_column(Date)
    primary_document: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(String(255), default="")


class FinancialFact(Base):
    """One reported XBRL value, exactly as filed (data.sec.gov companyfacts)."""

    __tablename__ = "financial_facts"
    __table_args__ = (Index("ix_facts_cik_concept", "cik", "concept"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cik: Mapped[int] = mapped_column(Integer, index=True)
    taxonomy: Mapped[str] = mapped_column(String(16))
    concept: Mapped[str] = mapped_column(String(160))
    unit: Mapped[str] = mapped_column(String(32))
    start: Mapped[date | None] = mapped_column(Date)
    end: Mapped[date] = mapped_column(Date)
    value: Mapped[Decimal] = mapped_column(DecimalString)
    accession: Mapped[str] = mapped_column(String(25))
    fy: Mapped[int | None] = mapped_column(Integer)
    fp: Mapped[str] = mapped_column(String(4), default="")
    form: Mapped[str] = mapped_column(String(20))
    filed: Mapped[date] = mapped_column(Date)
    frame: Mapped[str] = mapped_column(String(16), default="")


class PriceBar(Base):
    """End-of-day price bar. Never intraday / real-time."""

    __tablename__ = "price_bars"
    __table_args__ = (UniqueConstraint("ticker", "day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[Decimal | None] = mapped_column(DecimalString)
    high: Mapped[Decimal | None] = mapped_column(DecimalString)
    low: Mapped[Decimal | None] = mapped_column(DecimalString)
    close: Mapped[Decimal] = mapped_column(DecimalString)
    adj_close: Mapped[Decimal | None] = mapped_column(DecimalString)
    volume: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    source: Mapped[str] = mapped_column(String(48))
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ProviderUsage(Base):
    """Counts our own requests to rate-limited providers (one row per provider per hour)."""

    __tablename__ = "provider_usage"
    __table_args__ = (UniqueConstraint("provider", "hour"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    hour: Mapped[datetime] = mapped_column(UTCDateTime)
    requests: Mapped[int] = mapped_column(Integer, default=0)


class FxRate(Base):
    """ECB euro foreign exchange reference rates (1 EUR = value CURRENCY)."""

    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("currency", "day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), index=True)
    day: Mapped[date] = mapped_column(Date)
    value: Mapped[Decimal] = mapped_column(DecimalString)
    source: Mapped[str] = mapped_column(String(32), default="ecb_exr")


# ----------------------------------------------------------------- Phase 3
class AISettings(Base):
    """Per-user model choice. Empty = server default (II_OLLAMA_CHAT_MODEL / first installed)."""

    __tablename__ = "ai_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    chat_model: Mapped[str] = mapped_column(String(128), default="")
    embed_model: Mapped[str] = mapped_column(String(128), default="")
    temperature: Mapped[Decimal] = mapped_column(DecimalString, default=Decimal("0.2"))


class Document(Base):
    """A private PDF uploaded by a user (annual report, earnings release...)."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    security_id: Mapped[int | None] = mapped_column(ForeignKey("securities.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    pages: Mapped[int] = mapped_column(Integer, default=0)
    chars: Mapped[int] = mapped_column(Integer, default=0)
    # extracted | ocr | indexing | ready | keyword_only | error
    status: Mapped[str] = mapped_column(String(16), default="extracted")
    ocr_pages: Mapped[int] = mapped_column(Integer, default=0)  # pages whose text came from OCR
    ocr_language: Mapped[str] = mapped_column(String(64), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    embed_model: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    security: Mapped[Security | None] = relationship()


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (Index("ix_chunks_doc", "document_id", "seq"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    page: Mapped[int] = mapped_column(Integer)  # 1-based page where the chunk starts
    text: Mapped[str] = mapped_column(Text)
    ocr: Mapped[bool] = mapped_column(Boolean, default=False)  # text recognised by OCR (may contain errors)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary)  # float32 little-endian, L2-normalised


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="ChatMessage.id"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    task: Mapped[str] = mapped_column(String(32), default="ask")
    tickers: Mapped[str] = mapped_column(String(64), default="")  # comma separated
    document_ids: Mapped[str] = mapped_column(String(128), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    sources: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of cited sources
    verification: Mapped[str] = mapped_column(Text, default="{}")  # JSON number check
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | error | partial
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


# ----------------------------------------------------------------- Phase 4
class ScreenFact(Base):
    """One value per company from the SEC XBRL "frames" API (one concept, one calendar period, all filers)."""

    __tablename__ = "screen_facts"
    __table_args__ = (UniqueConstraint("period", "concept", "cik"), Index("ix_screen_period_concept", "period", "concept"))

    id: Mapped[int] = mapped_column(primary_key=True)
    period: Mapped[str] = mapped_column(String(12))  # CY2024 | CY2024Q4I
    concept: Mapped[str] = mapped_column(String(160))
    cik: Mapped[int] = mapped_column(Integer, index=True)
    entity_name: Mapped[str] = mapped_column(String(255), default="")
    value: Mapped[Decimal] = mapped_column(DecimalString)
    end: Mapped[date | None] = mapped_column(Date)
    accession: Mapped[str] = mapped_column(String(25), default="")


class Valuation(Base):
    """A saved DCF scenario. Inputs are the user's assumptions; private to the user."""

    __tablename__ = "valuations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    inputs: Mapped[str] = mapped_column(Text)  # JSON
    summary: Mapped[str] = mapped_column(Text)  # JSON
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ----------------------------------------------------------------- Phase 5
class Feed(Base):
    """An RSS/Atom feed added by an administrator (shared by all members)."""

    __tablename__ = "feeds"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(500), unique=True)
    title: Mapped[str] = mapped_column(String(160))
    ticker: Mapped[str | None] = mapped_column(String(20))  # optional: feed belongs to one company (e.g. IR press releases)
    etag: Mapped[str] = mapped_column(String(255), default="")
    last_modified: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="never")
    message: Mapped[str] = mapped_column(Text, default="")
    last_fetch_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class NewsItem(Base):
    __tablename__ = "news_items"
    __table_args__ = (UniqueConstraint("feed_id", "guid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    feed_id: Mapped[int] = mapped_column(ForeignKey("feeds.id", ondelete="CASCADE"), index=True)
    guid: Mapped[str] = mapped_column(String(500))
    title: Mapped[str] = mapped_column(String(500))
    link: Mapped[str] = mapped_column(String(1000))
    summary: Mapped[str] = mapped_column(Text, default="")  # short plain-text excerpt only
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Alert(Base):
    """A user's private alert.

    kinds: price_above | price_below | daily_move (abs % change between the last two stored closes)
           | filing (new SEC filing; ``forms`` optional comma list)
    """

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    threshold: Mapped[Decimal | None] = mapped_column(DecimalString)
    forms: Mapped[str] = mapped_column(String(80), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    repeat: Mapped[bool] = mapped_column(Boolean, default=False)  # re-arm after triggering
    note: Mapped[str] = mapped_column(String(200), default="")
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_triggered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_seen_marker: Mapped[str] = mapped_column(String(64), default="")  # last price date / accession evaluated
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class PushSubscription(Base):
    """A browser Web Push subscription (one per device), owned by a user."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(String(1000), unique=True)
    p256dh: Mapped[str] = mapped_column(String(255))
    auth: Mapped[str] = mapped_column(String(255))
    user_agent: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class JobRun(Base):
    """History of scheduled background jobs (visible to administrators)."""

    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(48), index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | ok | error
    message: Mapped[str] = mapped_column(Text, default="")


# ----------------------------------------------------------------- ESEF (EU annual reports)
class EsefFiling(Base):
    """One ESEF annual financial report (inline XBRL) that was imported."""

    __tablename__ = "esef_filings"
    __table_args__ = (UniqueConstraint("lei", "period_end", "sha256"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    lei: Mapped[str] = mapped_column(String(20), index=True)
    entity_name: Mapped[str] = mapped_column(String(255), default="")
    period_end: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(32))  # upload | filings.xbrl.org
    source_ref: Mapped[str] = mapped_column(String(500), default="")  # file name or filing URL
    viewer_url: Mapped[str] = mapped_column(String(500), default="")
    sha256: Mapped[str] = mapped_column(String(64))
    fact_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class EsefFact(Base):
    """A reported, non-dimensional numeric fact from an ESEF report, exactly as tagged."""

    __tablename__ = "esef_facts"
    __table_args__ = (Index("ix_esef_facts_lei_concept", "lei", "concept"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("esef_filings.id", ondelete="CASCADE"), index=True)
    lei: Mapped[str] = mapped_column(String(20))
    taxonomy: Mapped[str] = mapped_column(String(32))  # ifrs-full | company extension prefix
    concept: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(32))
    start: Mapped[date | None] = mapped_column(Date)
    end: Mapped[date] = mapped_column(Date)
    value: Mapped[Decimal] = mapped_column(DecimalString)


class OAuthClient(Base):
    """An OAuth client registered through Dynamic Client Registration (the Claude apps)."""

    __tablename__ = "oauth_clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client_name: Mapped[str] = mapped_column(String(200), default="")
    redirect_uris: Mapped[str] = mapped_column(Text)  # JSON list
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class OAuthCode(Base):
    """Short-lived, single-use authorization code (only its hash is stored)."""

    __tablename__ = "oauth_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    redirect_uri: Mapped[str] = mapped_column(Text)
    code_challenge: Mapped[str] = mapped_column(String(128))
    scope: Mapped[str] = mapped_column(String(200), default="")
    resource: Mapped[str] = mapped_column(String(500), default="")
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class OAuthGrant(Base):
    """Access a user gave to a connector client. Tokens are stored as SHA-256 hashes only;
    the refresh token rotates on every use."""

    __tablename__ = "oauth_grants"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    client_name: Mapped[str] = mapped_column(String(200), default="")
    scope: Mapped[str] = mapped_column(String(200), default="")
    access_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    access_expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    refresh_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    refresh_expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
