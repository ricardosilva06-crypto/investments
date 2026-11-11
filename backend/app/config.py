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

    # Local Ollama server (AI analyst). Nothing is sent to any paid/cloud AI.
    ollama_url: str = "http://127.0.0.1:11434"
    # Defaults when a user has not picked a model. Empty = first installed model.
    ollama_chat_model: str = ""
    ollama_embed_model: str = ""  # e.g. nomic-embed-text; empty = keyword search only
    ollama_num_ctx: int = 8192  # context window requested from the model
    ollama_timeout_seconds: int = 300

    # Background scheduler (daily refresh, alerts, feeds, backups). Runs inside this process.
    scheduler: bool = True
    # Hour (UTC) for the daily refresh + alert evaluation, and for the nightly backup.
    daily_job_hour_utc: int = 22
    backup_hour_utc: int = 3
    backups_keep: int = 14

    # Web Push (optional): VAPID keys are generated automatically on first use and stored in data_dir.
    # The contact is sent to browser push services (Google/Apple/Mozilla) as required by the protocol.
    vapid_contact: str = "mailto:admin@localhost"

    # Security hardening
    api_docs: bool = False  # expose /api/docs (OpenAPI UI); keep off when reachable remotely
    allowed_hosts: str = ""  # comma list, e.g. "myserver.tailnet.ts.net,localhost"; empty = any

    # Uploaded PDFs
    max_upload_mb: int = 25
    max_pdf_pages: int = 600

    # OCR for scanned PDFs (local Tesseract). "auto" = use it when installed, "off" = never.
    ocr: str = "auto"
    ocr_languages: str = "eng"  # Tesseract codes joined by '+', e.g. "eng+por+deu+fra"
    ocr_dpi: int = 300
    ocr_max_pages: int = 300

    # Optional end-of-day price provider (Tiingo free plan; personal/internal use).
    # Leave empty to rely on CSV imports only. Budget stays below Tiingo's free limits.
    tiingo_api_key: str = ""
    tiingo_max_per_hour: int = 40
    tiingo_max_per_day: int = 400

    # Minimum seconds between two syncs of the same data source.
    min_sync_interval_seconds: int = 3600

    @property
    def database_path(self) -> Path:
        return self.data_dir / "investor.db"

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"


@lru_cache
def get_settings() -> Settings:
    return Settings()
