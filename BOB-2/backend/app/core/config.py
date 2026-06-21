import secrets
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root, computed relative to this file so the app is portable across machines.
# config.py -> core -> app -> backend -> <project root>
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def generate_secret_key() -> str:
    """Generate a secure random secret key for production use."""
    return secrets.token_urlsafe(64)


class Settings(BaseSettings):
    APP_NAME: str = "GuardianAI Accountant & Auditor Enterprise"
    APP_ENV: str = "local"

    BACKEND_HOST: str = "127.0.0.1"
    BACKEND_PORT: int = 8000

    FRONTEND_ORIGIN: str = "http://localhost:3000"
    CORS_ORIGINS: str = ""  # Comma-separated additional origins
    TRUSTED_HOSTS: str = ""  # Comma-separated trusted hosts for production

    DATABASE_URL: str = "postgresql+psycopg2://guardian:guardian@localhost:5432/guardianai"

    # SECRET_KEY must be at least 32 characters for security.
    # In production set a strong random key (use: openssl rand -hex 64).
    # In local/dev mode a random key is generated each startup when unset.
    SECRET_KEY: str = ""

    # Token configuration
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30  # Reduced from 60 for better security
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Security settings
    MAX_LOGIN_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 30
    REQUIRE_HTTPS: bool = False  # Set to True in production

    # File upload security
    MAX_UPLOAD_SIZE_MB: int = 10
    ALLOWED_UPLOAD_EXTENSIONS: str = ".pdf,.png,.jpg,.jpeg,.gif,.webp,.txt,.csv"

    # Local storage directory (telegram config/uploads, etc). Defaults to <project root>/storage.
    STORAGE_DIR: str = str(PROJECT_ROOT / "storage")

    # LLM provider (xAI Grok) API key. Must be provided via environment / .env.
    GROK_API_KEY: str = ""

    @property
    def storage_path(self) -> Path:
        return Path(self.STORAGE_DIR)

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() in {"production", "prod"}

    @property
    def allowed_upload_extensions_list(self) -> list:
        return [ext.strip().lower() for ext in self.ALLOWED_UPLOAD_EXTENSIONS.split(",")]

    @property
    def cors_origin_list(self) -> list[str]:
        """All allowed CORS origins, de-duplicated."""
        origins = {self.FRONTEND_ORIGIN}
        if not self.is_production:
            origins.update(["http://localhost:3000", "http://127.0.0.1:3000"])
        if self.CORS_ORIGINS:
            origins.update(o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip())
        return sorted(origins)

    @property
    def trusted_host_list(self) -> list[str]:
        """Trusted hosts for TrustedHostMiddleware."""
        if self.TRUSTED_HOSTS:
            return [h.strip() for h in self.TRUSTED_HOSTS.split(",") if h.strip()]
        return ["localhost"]

    def validate_secret_key(self) -> None:
        """Validate that SECRET_KEY is secure enough for production."""
        if self.is_production:
            if len(self.SECRET_KEY) < 32:
                raise ValueError(
                    "SECRET_KEY must be at least 32 characters long in production. "
                    "Generate a secure key with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
                )
            if self.SECRET_KEY in ["", "CHANGE_ME", "CHANGE_ME_IN_PRODUCTION_MIN_32_CHARS_LONG", "your-secret-key", "secret"]:
                raise ValueError(
                    "SECRET_KEY cannot use default values in production. "
                    "Please set a strong random secret key."
                )

    def model_post_init(self, __context: object) -> None:
        if not self.SECRET_KEY:
            if self.is_production:
                raise ValueError(
                    "SECRET_KEY must be set in production. "
                    "Generate one with: openssl rand -hex 64"
                )
            # Auto-generate a random key for local/dev mode
            object.__setattr__(self, "SECRET_KEY", generate_secret_key())

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
