import ipaddress
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def generate_secret_key() -> str:
    return secrets.token_urlsafe(64)


class Settings(BaseSettings):
    APP_NAME: str = "GuardianAI Accountant & Auditor Enterprise"
    APP_ENV: str = "local"

    BACKEND_HOST: str = "127.0.0.1"
    BACKEND_PORT: int = 8000

    FRONTEND_ORIGIN: str = "http://localhost:3000"
    CORS_ORIGINS: str = ""
    TRUSTED_HOSTS: str = ""
    TRUSTED_PROXY_IPS: str = ""

    DATABASE_URL: str = "sqlite:///./guardianai.db"
    REDIS_URL: str = ""

    SECRET_KEY: str = ""

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 3

    MAX_LOGIN_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 30
    REQUIRE_HTTPS: bool = False

    GUARDIAN_SEED_EMAIL: str = ""
    GUARDIAN_SEED_PASSWORD: str = ""

    TELEGRAM_BOT_ENABLED: bool = False
    TELEGRAM_BOT_PRODUCTION_READY: bool = False
    TELEGRAM_ALLOW_GROUP_CHATS: bool = False
    TELEGRAM_APPROVAL_TTL_SECONDS: int = 600
    TELEGRAM_INGESTION_WORKERS: int = 2
    TELEGRAM_INGESTION_QUEUE_SIZE: int = 20
    TELEGRAM_MAX_PENDING_PER_ACTOR: int = 1
    TELEGRAM_MAX_PENDING_PER_ORGANIZATION: int = 5
    TELEGRAM_UPLOAD_RATE_LIMIT: int = 5
    TELEGRAM_UPLOAD_RATE_WINDOW_SECONDS: int = 60
    TELEGRAM_INGESTION_JOB_TTL_SECONDS: int = 300
    TELEGRAM_DOWNLOAD_TIMEOUT_SECONDS: int = 30
    TELEGRAM_DOWNLOAD_CHUNK_SIZE_BYTES: int = 65_536
    TELEGRAM_MESSAGE_MAX_AGE_SECONDS: int = 120
    TELEGRAM_API_RESPONSE_MAX_BYTES: int = 1_048_576

    # Tenant-configurable ERP destinations are denied unless explicitly allowlisted.
    ERP_OUTBOUND_REQUIRE_ALLOWLIST: bool = True
    ERP_OUTBOUND_ALLOWED_HOSTS: str = ""
    ERP_OUTBOUND_ALLOWED_CIDRS: str = ""
    ERP_OUTBOUND_ALLOWED_PORTS: str = "443"
    ERP_OUTBOUND_ALLOW_HTTP: bool = False
    ERP_OUTBOUND_CONNECT_TIMEOUT_SECONDS: int = 10
    ERP_OUTBOUND_READ_TIMEOUT_SECONDS: int = 30
    ERP_OUTBOUND_MAX_RESPONSE_BYTES: int = 10_485_760

    MAX_UPLOAD_SIZE_MB: int = 10
    MAX_REQUEST_SIZE_MB: int = 50
    MAX_UPLOAD_FILES: int = 20
    MAX_PDF_PAGES: int = 200
    MAX_IMAGE_PIXELS: int = 40_000_000
    MAX_ARCHIVE_FILES: int = 500
    MAX_ARCHIVE_UNCOMPRESSED_MB: int = 100
    OCR_TIMEOUT_SECONDS: int = 60
    ALLOWED_UPLOAD_EXTENSIONS: str = (
        ".pdf,.png,.jpg,.jpeg,.webp,.txt,.csv,.tsv,.xlsx,"
        ".ofx,.qfx,.qif,.mt940,.sta"
    )
    CLAMAV_HOST: str = ""
    CLAMAV_PORT: int = 3310
    REQUIRE_MALWARE_SCAN: bool = False

    STORAGE_DIR: str = str(PROJECT_ROOT / "storage")

    # Legacy LLM callers are local-only and never fall back to an Internet provider.
    LOCAL_LLM_ENABLED: bool = False
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "gemma2:9b"
    LOCAL_LLM_TIMEOUT_SECONDS: int = 120
    LOCAL_LLM_MAX_RESPONSE_BYTES: int = 1_048_576

    # External LLM is protected by both this global kill switch and a tenant policy row.
    EXTERNAL_LLM_ENABLED: bool = False
    EXTERNAL_LLM_REQUIRED_DPA_VERSION: str = "2026-07-v1"
    EXTERNAL_LLM_ALLOWED_PROVIDERS: str = "deepseek"
    EXTERNAL_LLM_ALLOWED_MODELS: str = "deepseek:deepseek-chat"
    EXTERNAL_LLM_ALLOWED_HOSTS: str = "api.deepseek.com"
    EXTERNAL_LLM_MAX_REQUEST_BYTES: int = 262_144
    EXTERNAL_LLM_MAX_RESPONSE_BYTES: int = 1_048_576
    EXTERNAL_LLM_MAX_REDACTED_TEXT_CHARS: int = 4_000

    DEEPSEEK_API_KEY: str = ""
    ACCOUNTING_LLM_PROVIDER: str = "deepseek"
    ACCOUNTING_LLM_MODEL: str = "deepseek-chat"
    ACCOUNTING_LLM_API_URL: str = "https://api.deepseek.com/chat/completions"
    ACCOUNTING_LLM_API_KEY: str = ""
    ACCOUNTING_LLM_TIMEOUT_SECONDS: int = 45

    EMBEDDING_MODEL_NAME: str = "BAAI/bge-m3"

    @property
    def storage_path(self) -> Path:
        return Path(self.STORAGE_DIR)

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

    def _validate_erp_outbound_configuration(self, errors: list[str]) -> None:
        hosts = [item.strip() for item in self.ERP_OUTBOUND_ALLOWED_HOSTS.split(",") if item.strip()]
        if not self.ERP_OUTBOUND_REQUIRE_ALLOWLIST:
            errors.append("ERP_OUTBOUND_REQUIRE_ALLOWLIST must be true")
        if not hosts:
            errors.append("ERP_OUTBOUND_ALLOWED_HOSTS is required")
        if any(host == "*" for host in hosts):
            errors.append("ERP_OUTBOUND_ALLOWED_HOSTS cannot contain a global wildcard")
        if self.ERP_OUTBOUND_ALLOW_HTTP:
            errors.append("ERP_OUTBOUND_ALLOW_HTTP must be false in production")

        raw_ports = [item.strip() for item in self.ERP_OUTBOUND_ALLOWED_PORTS.split(",") if item.strip()]
        if not raw_ports:
            errors.append("ERP_OUTBOUND_ALLOWED_PORTS cannot be empty")
        for raw_port in raw_ports:
            try:
                port = int(raw_port)
            except ValueError:
                errors.append("ERP_OUTBOUND_ALLOWED_PORTS contains an invalid port")
                break
            if not 1 <= port <= 65535:
                errors.append("ERP_OUTBOUND_ALLOWED_PORTS contains an out-of-range port")
                break

        private_supernets = (
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
            ipaddress.ip_network("100.64.0.0/10"),
            ipaddress.ip_network("fc00::/7"),
        )
        for raw_cidr in [item.strip() for item in self.ERP_OUTBOUND_ALLOWED_CIDRS.split(",") if item.strip()]:
            try:
                network = ipaddress.ip_network(raw_cidr, strict=True)
            except ValueError:
                errors.append("ERP_OUTBOUND_ALLOWED_CIDRS contains an invalid network")
                break
            if not any(
                network.version == supernet.version and network.subnet_of(supernet)
                for supernet in private_supernets
            ):
                errors.append("ERP_OUTBOUND_ALLOWED_CIDRS must contain only an explicit private network")
                break

        if not 1 <= self.ERP_OUTBOUND_CONNECT_TIMEOUT_SECONDS <= 30:
            errors.append("ERP_OUTBOUND_CONNECT_TIMEOUT_SECONDS must be between 1 and 30")
        if not 1 <= self.ERP_OUTBOUND_READ_TIMEOUT_SECONDS <= 120:
            errors.append("ERP_OUTBOUND_READ_TIMEOUT_SECONDS must be between 1 and 120")
        if not 65_536 <= self.ERP_OUTBOUND_MAX_RESPONSE_BYTES <= 52_428_800:
            errors.append("ERP_OUTBOUND_MAX_RESPONSE_BYTES must be between 65536 and 52428800")

    def _validate_llm_configuration(self, errors: list[str]) -> None:
        if not 5 <= self.LOCAL_LLM_TIMEOUT_SECONDS <= 300:
            errors.append("LOCAL_LLM_TIMEOUT_SECONDS must be between 5 and 300")
        if not 65_536 <= self.LOCAL_LLM_MAX_RESPONSE_BYTES <= 4_194_304:
            errors.append("LOCAL_LLM_MAX_RESPONSE_BYTES must be between 65536 and 4194304")
        if self.LOCAL_LLM_ENABLED:
            try:
                local_url = urlsplit(self.OLLAMA_BASE_URL)
            except ValueError:
                local_url = None
            if (
                local_url is None
                or local_url.scheme not in {"http", "https"}
                or (local_url.hostname or "").lower() not in {"localhost", "127.0.0.1", "::1"}
                or local_url.username is not None
                or local_url.password is not None
                or local_url.query
                or local_url.fragment
            ):
                errors.append("OLLAMA_BASE_URL must be a loopback-only URL")

        if not 5 <= self.ACCOUNTING_LLM_TIMEOUT_SECONDS <= 120:
            errors.append("ACCOUNTING_LLM_TIMEOUT_SECONDS must be between 5 and 120")
        if not 16_384 <= self.EXTERNAL_LLM_MAX_REQUEST_BYTES <= 1_048_576:
            errors.append("EXTERNAL_LLM_MAX_REQUEST_BYTES must be between 16384 and 1048576")
        if not 65_536 <= self.EXTERNAL_LLM_MAX_RESPONSE_BYTES <= 4_194_304:
            errors.append("EXTERNAL_LLM_MAX_RESPONSE_BYTES must be between 65536 and 4194304")
        if not 0 <= self.EXTERNAL_LLM_MAX_REDACTED_TEXT_CHARS <= 8_000:
            errors.append("EXTERNAL_LLM_MAX_REDACTED_TEXT_CHARS must be between 0 and 8000")

        if self.EXTERNAL_LLM_ENABLED:
            providers = [item.strip().lower() for item in self.EXTERNAL_LLM_ALLOWED_PROVIDERS.split(",") if item.strip()]
            models = [item.strip().lower() for item in self.EXTERNAL_LLM_ALLOWED_MODELS.split(",") if item.strip()]
            hosts = [item.strip().lower() for item in self.EXTERNAL_LLM_ALLOWED_HOSTS.split(",") if item.strip()]
            if not providers or "*" in providers:
                errors.append("EXTERNAL_LLM_ALLOWED_PROVIDERS requires an explicit allowlist")
            if not models or "*" in models:
                errors.append("EXTERNAL_LLM_ALLOWED_MODELS requires explicit provider:model pairs")
            if not hosts or "*" in hosts:
                errors.append("EXTERNAL_LLM_ALLOWED_HOSTS requires exact hosts")
            if not self.EXTERNAL_LLM_REQUIRED_DPA_VERSION.strip():
                errors.append("EXTERNAL_LLM_REQUIRED_DPA_VERSION is required")
            if not (self.ACCOUNTING_LLM_API_KEY or self.DEEPSEEK_API_KEY):
                errors.append("An external LLM API key is required when EXTERNAL_LLM_ENABLED is true")
            try:
                endpoint = urlsplit(self.ACCOUNTING_LLM_API_URL)
            except ValueError:
                endpoint = None
            if (
                endpoint is None
                or endpoint.scheme.lower() != "https"
                or (endpoint.hostname or "").lower() not in set(hosts)
                or (endpoint.port not in {None, 443})
                or endpoint.username is not None
                or endpoint.password is not None
                or endpoint.query
                or endpoint.fragment
                or not endpoint.path.endswith("/chat/completions")
            ):
                errors.append("ACCOUNTING_LLM_API_URL must be an approved HTTPS chat-completions endpoint")

    def validate_runtime_security(self) -> None:
        if not self.is_production:
            return

        self.validate_secret_key()
        errors: list[str] = []
        if not self.TRUSTED_HOSTS.strip():
            errors.append("TRUSTED_HOSTS is required")
        if not self.TRUSTED_PROXY_IPS.strip():
            errors.append("TRUSTED_PROXY_IPS is required")
        if not self.REQUIRE_HTTPS:
            errors.append("REQUIRE_HTTPS must be true")
        if not self.REDIS_URL.strip():
            errors.append("REDIS_URL is required for shared authentication rate limiting")
        if self.FRONTEND_ORIGIN.lower().startswith("http://"):
            errors.append("FRONTEND_ORIGIN must use https")
        if not self.REQUIRE_MALWARE_SCAN:
            errors.append("REQUIRE_MALWARE_SCAN must be true")
        if self.REQUIRE_MALWARE_SCAN and not self.CLAMAV_HOST.strip():
            errors.append("CLAMAV_HOST is required when malware scanning is enabled")
        if self.MAX_UPLOAD_SIZE_MB <= 0 or self.MAX_REQUEST_SIZE_MB < self.MAX_UPLOAD_SIZE_MB:
            errors.append("MAX_REQUEST_SIZE_MB must be at least MAX_UPLOAD_SIZE_MB and both must be positive")
        if self.MAX_UPLOAD_FILES <= 0 or self.MAX_UPLOAD_FILES > 100:
            errors.append("MAX_UPLOAD_FILES must be between 1 and 100")
        if self.TELEGRAM_ALLOW_GROUP_CHATS and not self.TELEGRAM_BOT_PRODUCTION_READY:
            errors.append(
                "TELEGRAM_ALLOW_GROUP_CHATS cannot be enabled before Telegram production readiness"
            )
        if not 60 <= self.TELEGRAM_APPROVAL_TTL_SECONDS <= 3600:
            errors.append("TELEGRAM_APPROVAL_TTL_SECONDS must be between 60 and 3600")
        if not 1 <= self.TELEGRAM_INGESTION_WORKERS <= 8:
            errors.append("TELEGRAM_INGESTION_WORKERS must be between 1 and 8")
        if not 1 <= self.TELEGRAM_INGESTION_QUEUE_SIZE <= 200:
            errors.append("TELEGRAM_INGESTION_QUEUE_SIZE must be between 1 and 200")
        if not 1 <= self.TELEGRAM_MAX_PENDING_PER_ACTOR <= 5:
            errors.append("TELEGRAM_MAX_PENDING_PER_ACTOR must be between 1 and 5")
        if not self.TELEGRAM_MAX_PENDING_PER_ACTOR <= self.TELEGRAM_MAX_PENDING_PER_ORGANIZATION <= self.TELEGRAM_INGESTION_QUEUE_SIZE:
            errors.append(
                "Telegram organization pending limit must be between the actor limit and queue size"
            )
        if not 1 <= self.TELEGRAM_UPLOAD_RATE_LIMIT <= 60:
            errors.append("TELEGRAM_UPLOAD_RATE_LIMIT must be between 1 and 60")
        if not 10 <= self.TELEGRAM_UPLOAD_RATE_WINDOW_SECONDS <= 3600:
            errors.append("TELEGRAM_UPLOAD_RATE_WINDOW_SECONDS must be between 10 and 3600")
        if not 30 <= self.TELEGRAM_INGESTION_JOB_TTL_SECONDS <= 1800:
            errors.append("TELEGRAM_INGESTION_JOB_TTL_SECONDS must be between 30 and 1800")
        if not 5 <= self.TELEGRAM_DOWNLOAD_TIMEOUT_SECONDS <= 120:
            errors.append("TELEGRAM_DOWNLOAD_TIMEOUT_SECONDS must be between 5 and 120")
        if not 16_384 <= self.TELEGRAM_DOWNLOAD_CHUNK_SIZE_BYTES <= 1_048_576:
            errors.append("TELEGRAM_DOWNLOAD_CHUNK_SIZE_BYTES must be between 16384 and 1048576")
        if not 30 <= self.TELEGRAM_MESSAGE_MAX_AGE_SECONDS <= 600:
            errors.append("TELEGRAM_MESSAGE_MAX_AGE_SECONDS must be between 30 and 600")
        if not 65_536 <= self.TELEGRAM_API_RESPONSE_MAX_BYTES <= 4_194_304:
            errors.append("TELEGRAM_API_RESPONSE_MAX_BYTES must be between 65536 and 4194304")

        self._validate_erp_outbound_configuration(errors)
        self._validate_llm_configuration(errors)

        database_url_lower = self.DATABASE_URL.lower()
        if database_url_lower.startswith("sqlite"):
            errors.append("SQLite is not allowed in production")
        if "guardian:guardian@" in database_url_lower:
            errors.append("default database credentials are forbidden")

        if self.GUARDIAN_SEED_EMAIL or self.GUARDIAN_SEED_PASSWORD:
            errors.append("automatic owner seeding is forbidden in production")
        if self.GUARDIAN_SEED_PASSWORD.lower() in {"guardian", "password"}:
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
