"""Application settings.

Every setting can be provided through environment variables prefixed with
``II_`` (for example ``II_SEC_USER_AGENT``) or through a ``.env`` file in the
backend directory. No setting requires a paid service.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="II_", env_file=BACKEND_DIR / ".env", extra="ignore")

    # Where the SQLite database and backups live.
    data_dir: Path = BACKEND_DIR / "data"

    # SEC EDGAR requires automated clients to identify themselves with a
    # User-Agent containing a name and a contact e-mail address, e.g.
    # "InvestorIntelligence (private use) you@example.com". Sync is refused
    # until this is set, so we never make anonymous requests to the SEC.
    sec_user_agent: str = ""

    # Session cookie settings. Set II_COOKIE_SECURE=true when the app is served
    # over HTTPS (e.g. via `tailscale serve` or Caddy). Required for iOS PWA.
    cookie_secure: bool = False
    session_days: int = 30

    # Built frontend (Next.js static export). Served by FastAPI if present.
    frontend_dist: Path = BACKEND_DIR.parent / "frontend" / "out"

    # Local Ollama server (Phase 3). Only used for an availability check now.
    ollama_url: str = "http://127.0.0.1:11434"

    # Minimum seconds between two syncs of the same data source.
    min_sync_interval_seconds: int = 3600

    @property
    def database_path(self) -> Path:
        return self.data_dir / "investor.db"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"


@lru_cache
def get_settings() -> Settings:
    return Settings()
