import time
import json
from datetime import datetime, timezone
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Middleware to log sensitive HTTP actions to the database."""

    # Paths to exclude from audit logging (health checks, static files, etc.)
    EXCLUDED_PATHS = {"/health", "/docs", "/redoc", "/openapi.json", "/favicon.ico"}
    # Paths that contain sensitive data that should be masked
    SENSITIVE_PATHS = {"/login", "/refresh", "/api/v1/auth/login"}

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        # Generate request ID for tracing
        request_id = f"req_{int(time.time() * 1000)}_{id(request)}"
        request.state.request_id = request_id

        response = await call_next(request)

        duration_ms = round((time.time() - start_time) * 1000, 2)

        # Skip logging for excluded paths
        if request.url.path in self.EXCLUDED_PATHS:
            return response

        # Only log state-changing operations or errors
        should_log = (
            request.method in {"POST", "PUT", "PATCH", "DELETE"} or
            response.status_code >= 400
        )

        if should_log:
            await self._persist_audit_log(request, response, duration_ms)

        # Add request ID to response headers for tracing
        response.headers["X-Request-ID"] = request_id

        return response

    async def _persist_audit_log(self, request: Request, response, duration_ms: float):
        """Persist audit log entry to database."""
        try:
            # Get client IP with proxy support
            client_ip = self._get_client_ip(request)

            # Get user info if available from auth token
            user_id = None
            organization_id = None
            try:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    from app.security.auth import decode_access_token
                    token = auth_header.replace("Bearer ", "")
                    payload = decode_access_token(token)
                    # Try to get user ID from database
                    db = SessionLocal()
                    try:
                        from app.models.core import User  # noqa: F811
                        user = db.query(User).filter(User.email == payload.get("sub")).first()
                        if user:
                            user_id = user.id
                            organization_id = user.organization_id
                    finally:
                        db.close()
            except Exception:
                pass  # User not authenticated or token invalid

            # Mask sensitive paths
            path = request.url.path
            if any(sensitive in path for sensitive in self.SENSITIVE_PATHS):
                path = f"{path} [MASKED]"

            # Create audit log entry
            from app.db.database import SessionLocal
            from app.models.core import AuditLog
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
                        "user_agent": request.headers.get("User-Agent", "")[:200],  # Limit length
                    }
                )
                db.add(audit_entry)
                db.commit()
            except Exception as e:
                # If DB logging fails, fall back to console
                print(f"[Audit Log] DB persistence failed: {e}")
                self._fallback_log(request, response, duration_ms, client_ip)
            finally:
                db.close()

        except Exception as e:
            # Don't let audit logging break the application
            print(f"[Audit Log] Error: {e}")

    def _get_client_ip(self, request: Request) -> str:
        """Get client IP with proxy support."""
        # Check for X-Forwarded-For header
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        # Check for X-Real-IP header
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fall back to direct client
        return request.client.host if request.client else "unknown"

    def _fallback_log(self, request: Request, response, duration_ms: float, client_ip: str):
        """Fallback console logging if database is unavailable."""
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "audit_event": "http_action",
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "client": client_ip,
        }
        print(f"[AUDIT] {json.dumps(log_entry)}")
