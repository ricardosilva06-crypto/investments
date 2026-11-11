"""SQLite database setup (SQLAlchemy 2.0)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import String, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import DateTime, TypeDecorator

from .config import get_settings


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    """Stores datetimes as naive UTC in SQLite and returns aware UTC values."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetimes are not allowed; use UTC-aware values")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class DecimalString(TypeDecorator):
    """Exact decimal storage. SQLite has no DECIMAL type; REAL would lose precision."""

    impl = String(64)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        try:
            d = Decimal(value)
        except (InvalidOperation, TypeError) as exc:
            raise ValueError(f"Invalid decimal: {value!r}") from exc
        return format(d.normalize(), "f")

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)


def utcnow() -> datetime:
    return datetime.now(UTC)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record):  # pragma: no cover - trivial
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{settings.database_path}",
            connect_args={"check_same_thread": False},
        )
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def reset_engine() -> None:
    """Used by tests to point the app at a fresh database."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


# Columns added after a table first shipped. create_all() never alters existing
# tables, so these are added in place (additive only, never destructive).
ADDED_COLUMNS = [
    ("notes", "is_shared", "BOOLEAN NOT NULL DEFAULT 0"),
]


def _ensure_columns(conn) -> None:
    for table, column, ddl in ADDED_COLUMNS:
        cols = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
        if cols and column not in cols:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db() -> None:
    from . import models  # noqa: F401  (registers tables)

    Base.metadata.create_all(get_engine())
    with get_engine().begin() as conn:
        _ensure_columns(conn)
    with get_engine().begin() as conn:
        # Full-text index for document chunks (SQLite FTS5, local).
        conn.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(body, tokenize='porter unicode61')")


def session_factory() -> sessionmaker:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_db() -> Iterator[Session]:
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()
