"""
Rate limiting utility for authentication endpoints.
Prevents brute force attacks by limiting login attempts.

NOTE — Scaling:
    This implementation stores state in-process memory.  It works correctly
    for single-instance deployments.  For horizontally-scaled deployments
    behind a load-balancer, replace this with a Redis-backed store so that
    counters are shared across all backend instances.  The public interface
    (record_attempt / is_locked_out / check_rate_limit) stays the same.
"""
import time
from collections import defaultdict
from typing import Dict, Tuple
from fastapi import HTTPException, status
from app.core.config import settings


class LoginRateLimiter:
    """In-memory rate limiter for login attempts."""

    def __init__(self):
        self._attempts: Dict[str, list] = defaultdict(list)
        self._lockouts: Dict[str, float] = {}  # {identifier: lockout_until_timestamp}

    def _clean_old_attempts(self, identifier: str) -> None:
        """Remove attempts older than the lockout window."""
        now = time.time()
        window_seconds = settings.LOGIN_LOCKOUT_MINUTES * 60
        self._attempts[identifier] = [
            (ts, count) for ts, count in self._attempts[identifier]
            if now - ts < window_seconds
        ]

    def is_locked_out(self, identifier: str) -> Tuple[bool, int]:
        """
        Check if an identifier (IP or email) is currently locked out.
        Returns (is_locked, remaining_seconds).
        """
        now = time.time()

        # Check explicit lockout
        if identifier in self._lockouts:
            if now < self._lockouts[identifier]:
                remaining = int(self._lockouts[identifier] - now)
                return True, remaining
            else:
                # Lockout expired
                del self._lockouts[identifier]

        # Check attempt-based lockout
        self._clean_old_attempts(identifier)
        total_attempts = sum(count for _, count in self._attempts[identifier])

        if total_attempts >= settings.MAX_LOGIN_ATTEMPTS:
            # Lock out the identifier
            lockout_until = now + (settings.LOGIN_LOCKOUT_MINUTES * 60)
            self._lockouts[identifier] = lockout_until
            remaining = int(lockout_until - now)
            return True, remaining

        return False, 0

    def record_attempt(self, identifier: str, success: bool) -> None:
        """Record a login attempt."""
        if success:
            # Clear failed attempts on success
            self._attempts[identifier] = []
            if identifier in self._lockouts:
                del self._lockouts[identifier]
        else:
            now = time.time()
            self._attempts[identifier].append((now, 1))
            self._clean_old_attempts(identifier)

    def check_rate_limit(self, identifier: str) -> None:
        """
        Check if rate limit is exceeded and raise HTTPException if so.
        Use this at the beginning of login endpoints.
        """
        is_locked, remaining = self.is_locked_out(identifier)
        if is_locked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed login attempts. Please try again in {remaining // 60} minutes.",
            )


# Global rate limiter instance
login_rate_limiter = LoginRateLimiter()


def get_client_identifier(request) -> str:
    """
    Get a unique identifier for rate limiting from the request.
    Uses X-Forwarded-For if available (for proxied requests), otherwise client host.
    """
    # Check for X-Forwarded-For header (common in proxied environments)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first IP in the chain (client IP)
        return forwarded_for.split(",")[0].strip()

    # Check for X-Real-IP header
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    # Fall back to direct client host
    return request.client.host if request.client else "unknown"
