import json
import logging
import secrets
import time
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.db.database import SessionLocal
from app.models.core import AuditLog, User
from app.security.auth import decode_access_token
from app.security.rate_limiter import get_client_identifier

logger = logging.getLogger(__name__)


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Persist security-relevant HTTP actions without logging secrets."""

    EXCLUDED_PATHS = {"/health", "/docs", "/redoc", "/openapi.json", "/favicon.ico"}
    SENSITIVE_PATHS = {
        "/login",
        "/refresh",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
    }

    async def dispatch(self, request: Request, call_next):
        start_time = time.monotonic()
        request_id = f"req_{secrets.token_hex(16)}"
        request.state.request_id = request_id

        response = await call_next(request)
        duration_ms = round((time.monotonic() - start_time) * 1000, 2)

        if request.url.path not in self.EXCLUDED_PATHS:
            should_log = (
                request.method in {"POST", "PUT", "PATCH", "DELETE"}
                or response.status_code >= 400
            )
            if should_log:
                self._persist_audit_log(request, response, duration_ms)

        response.headers["X-Request-ID"] = request_id
        return response

    def _resolve_actor(self, request: Request) -> tuple[int | None, int | None]:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return None, None

        try:
            payload = decode_access_token(auth_header.removeprefix("Bearer ").strip())
        except Exception:
            return None, None

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == payload.get("sub")).first()
            if not user:
                return None, None
            return user.id, user.organization_id
        except Exception:
            logger.exception("Failed to resolve audit actor")
            return None, None
        finally:
            db.close()

    def _persist_audit_log(self, request: Request, response, duration_ms: float) -> None:
        client_ip = get_client_identifier(request)
        user_id, organization_id = self._resolve_actor(request)

        path = request.url.path
        if any(sensitive in path for sensitive in self.SENSITIVE_PATHS):
            path = f"{path} [MASKED]"

        db = SessionLocal()
        try:
            audit_entry = AuditLog(
                organization_id=organization_id,
                user_id=user_id,
                action=f"{request.method} {path}",
                entity_type="http_request",
                entity_id=request.state.request_id,
                ip_address=client_ip,
                details={
                    "method": request.method,
                    "path": path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    "user_agent": request.headers.get("User-Agent", "")[:200],
                },
            )
            db.add(audit_entry)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Audit database persistence failed")
            self._fallback_log(request, response, duration_ms, client_ip)
        finally:
            db.close()

    @staticmethod
    def _fallback_log(request: Request, response, duration_ms: float, client_ip: str) -> None:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "audit_event": "http_action",
            "request_id": getattr(request.state, "request_id", "unknown"),
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "client": client_ip,
        }
        logger.error("AUDIT_FALLBACK %s", json.dumps(log_entry, ensure_ascii=False))
