"""Authentication rate limiting.

The limiter is intentionally conservative about client identity: proxy headers are
not trusted here. A trusted reverse proxy must normalize the socket peer address
before requests reach the application. Replace the in-memory store with Redis
before horizontally scaling the backend.
"""
import time
from collections import defaultdict
from typing import Dict, Tuple

from fastapi import HTTPException, status

from app.core.config import settings


class LoginRateLimiter:
    def __init__(self):
        self._attempts: Dict[str, list] = defaultdict(list)
        self._lockouts: Dict[str, float] = {}

    def _clean_old_attempts(self, identifier: str) -> None:
        now = time.time()
        window_seconds = settings.LOGIN_LOCKOUT_MINUTES * 60
        self._attempts[identifier] = [
            (ts, count)
            for ts, count in self._attempts[identifier]
            if now - ts < window_seconds
        ]

    def is_locked_out(self, identifier: str) -> Tuple[bool, int]:
        now = time.time()
        if identifier in self._lockouts:
            if now < self._lockouts[identifier]:
                return True, int(self._lockouts[identifier] - now)
            del self._lockouts[identifier]

        self._clean_old_attempts(identifier)
        if sum(count for _, count in self._attempts[identifier]) >= settings.MAX_LOGIN_ATTEMPTS:
            lockout_until = now + settings.LOGIN_LOCKOUT_MINUTES * 60
            self._lockouts[identifier] = lockout_until
            return True, int(lockout_until - now)
        return False, 0

    def record_attempt(self, identifier: str, success: bool) -> None:
        if success:
            self._attempts.pop(identifier, None)
            self._lockouts.pop(identifier, None)
            return
        self._attempts[identifier].append((time.time(), 1))
        self._clean_old_attempts(identifier)

    def check_rate_limit(self, identifier: str) -> None:
        is_locked, remaining = self.is_locked_out(identifier)
        if is_locked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed login attempts. Please try again in {max(1, remaining // 60)} minutes.",
            )


login_rate_limiter = LoginRateLimiter()


def get_client_identifier(request) -> str:
    """Use only the actual socket peer address.

    Never consume X-Forwarded-For or X-Real-IP directly in application code;
    clients can forge them. Configure an allowlisted reverse proxy/Uvicorn
    forwarded-allow-ips setting so the trusted proxy supplies the real peer.
    """
    return request.client.host if request.client else "unknown"
