import secrets
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root, computed relative to this file so the app is portable across machines.
# config.py -> core -> app -> backend -> <project root>
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def generate_secret_key() -> str:
    """Generate a secure random secret key for local development."""
    return secrets.token_urlsafe(64)


class Settings(BaseSettings):
    APP_NAME: str = "GuardianAI Accountant & Auditor Enterprise"
    APP_ENV: str = "local"

    BACKEND_HOST: str = "127.0.0.1"
    BACKEND_PORT: int = 8000

    FRONTEND_ORIGIN: str = "http://localhost:3000"
    CORS_ORIGINS: str = ""
    TRUSTED_HOSTS: str = ""
    # Only direct peers in these IPs/CIDRs may supply X-Forwarded-For/X-Real-IP.
    TRUSTED_PROXY_IPS: str = ""

    # Local development uses SQLite unless an explicit database URL is provided.
    # Production validation rejects SQLite and known/default credentials.
    DATABASE_URL: str = "sqlite:///./guardianai.db"
    REDIS_URL: str = ""

    # SECRET_KEY must be at least 32 characters in production.
    SECRET_KEY: str = ""

    # Token configuration
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 3

    # Security settings
    MAX_LOGIN_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 30
    REQUIRE_HTTPS: bool = False

    # Optional development-only bootstrap. Production never auto-creates an owner.
    GUARDIAN_SEED_PASSWORD: str = ""

    # File upload security
    MAX_UPLOAD_SIZE_MB: int = 10
    MAX_PDF_PAGES: int = 200
    MAX_IMAGE_PIXELS: int = 40_000_000
    MAX_ARCHIVE_FILES: int = 500
    MAX_ARCHIVE_UNCOMPRESSED_MB: int = 100
    OCR_TIMEOUT_SECONDS: int = 60
    ALLOWED_UPLOAD_EXTENSIONS: str = (
        ".pdf,.png,.jpg,.jpeg,.webp,.txt,.csv,.tsv,.xlsx,.xls,"
        ".ofx,.qfx,.qif,.mt940,.sta"
    )

    # Local storage directory (telegram config/uploads, etc).
    STORAGE_DIR: str = str(PROJECT_ROOT / "storage")

    # LLM provider (DeepSeek) API key. Must be provided via environment / .env.
    DEEPSEEK_API_KEY: str = ""

    ACCOUNTING_LLM_PROVIDER: str = "deepseek"
    ACCOUNTING_LLM_MODEL: str = "deepseek-chat"
    ACCOUNTING_LLM_API_URL: str = "https://api.deepseek.com/chat/completions"
    ACCOUNTING_LLM_API_KEY: str = ""
    ACCOUNTING_LLM_TIMEOUT_SECONDS: int = 45

    EMBEDDING_MODEL_NAME: str = "BAAI/bge-m3"
    CHROMA_PERSIST_DIR: str = ""

    @property
    def storage_path(self) -> Path:
        return Path(self.STORAGE_DIR)

    @property
    def chroma_persist_path(self) -> str:
        if self.CHROMA_PERSIST_DIR:
            return self.CHROMA_PERSIST_DIR
        return str(self.storage_path / "chroma_db")

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() in {"production", "prod"}

    @property
    def allowed_upload_extensions_list(self) -> list[str]:
        return [
            ext.strip().lower()
            for ext in self.ALLOWED_UPLOAD_EXTENSIONS.split(",")
            if ext.strip()
        ]

    @property
    def cors_origin_list(self) -> list[str]:
        """All allowed CORS origins, de-duplicated."""
        origins = {self.FRONTEND_ORIGIN}
        if not self.is_production:
            origins.update(["http://localhost:3000", "http://127.0.0.1:3000"])
        if self.CORS_ORIGINS:
            origins.update(o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip())
        return sorted(origin for origin in origins if origin)

    @property
    def trusted_host_list(self) -> list[str]:
        return [h.strip() for h in self.TRUSTED_HOSTS.split(",") if h.strip()]

    @property
    def trusted_proxy_list(self) -> list[str]:
        return [h.strip() for h in self.TRUSTED_PROXY_IPS.split(",") if h.strip()]

    def validate_secret_key(self) -> None:
        if not self.is_production:
            return
        insecure_values = {
            "",
            "CHANGE_ME",
            "CHANGE_ME_IN_PRODUCTION_MIN_32_CHARS_LONG",
            "your-secret-key",
            "secret",
        }
        if len(self.SECRET_KEY) < 32 or self.SECRET_KEY in insecure_values:
            raise ValueError(
                "SECRET_KEY must be a non-default value of at least 32 characters in production. "
                "Generate one with: openssl rand -hex 64"
            )

    def validate_runtime_security(self) -> None:
        """Fail closed when production security controls are missing."""
        if not self.is_production:
            return

        self.validate_secret_key()

        errors: list[str] = []
        if not self.TRUSTED_HOSTS.strip():
            errors.append("TRUSTED_HOSTS is required")
        if not self.REQUIRE_HTTPS:
            errors.append("REQUIRE_HTTPS must be true")
        if not self.REDIS_URL.strip():
            errors.append("REDIS_URL is required for shared authentication rate limiting")
        if self.FRONTEND_ORIGIN.lower().startswith("http://"):
            errors.append("FRONTEND_ORIGIN must use https")

        database_url_lower = self.DATABASE_URL.lower()
        if database_url_lower.startswith("sqlite"):
            errors.append("SQLite is not allowed in production")
        if "guardian:guardian@" in database_url_lower:
            errors.append("default database credentials are forbidden")

        if self.GUARDIAN_SEED_PASSWORD in {"Owner@Seed#2026!", "guardian", "password"}:
            errors.append("known/default seed passwords are forbidden")

        if errors:
            raise ValueError("Unsafe production configuration: " + "; ".join(errors))

    def model_post_init(self, __context: object) -> None:
        db_url = self.DATABASE_URL
        if db_url.startswith("postgresql://"):
            object.__setattr__(
                self,
                "DATABASE_URL",
                db_url.replace("postgresql://", "postgresql+psycopg2://", 1),
            )

        if not self.SECRET_KEY:
            if self.is_production:
                raise ValueError(
                    "SECRET_KEY must be set in production. Generate one with: openssl rand -hex 64"
                )
            object.__setattr__(self, "SECRET_KEY", generate_secret_key())

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
