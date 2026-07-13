"""Shared authentication rate limiting with trusted-proxy IP handling."""

import hashlib
import ipaddress
import logging
import time
from collections import defaultdict
from typing import Dict, Tuple

from fastapi import HTTPException, status

from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    from redis import Redis
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - deployment installs redis dependency
    Redis = None  # type: ignore[assignment]
    RedisError = Exception  # type: ignore[assignment]


class LoginRateLimiter:
    """Redis-backed limiter in production with a local-only development fallback."""

    def __init__(self) -> None:
        self._attempts: Dict[str, list] = defaultdict(list)
        self._lockouts: Dict[str, float] = {}
        self._redis = None
        if settings.REDIS_URL and Redis is not None:
            self._redis = Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
                health_check_interval=30,
            )

    @staticmethod
    def _key(identifier: str) -> str:
        digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
        return f"guardian:auth:failed:{digest}"

    @property
    def _window_seconds(self) -> int:
        return settings.LOGIN_LOCKOUT_MINUTES * 60

    def _redis_unavailable(self, exc: Exception) -> None:
        logger.error("Redis rate limiter unavailable: %s", exc)
        if settings.is_production:
            # Authentication must fail closed if the shared abuse-control store is down.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service temporarily unavailable.",
                headers={"Retry-After": "60"},
            )

    def _clean_old_attempts(self, identifier: str) -> None:
        now = time.time()
        self._attempts[identifier] = [
            (ts, count)
            for ts, count in self._attempts[identifier]
            if now - ts < self._window_seconds
        ]

    def _local_is_locked_out(self, identifier: str) -> Tuple[bool, int]:
        now = time.time()
        if identifier in self._lockouts:
            if now < self._lockouts[identifier]:
                return True, int(self._lockouts[identifier] - now)
            del self._lockouts[identifier]

        self._clean_old_attempts(identifier)
        total_attempts = sum(count for _, count in self._attempts[identifier])
        if total_attempts >= settings.MAX_LOGIN_ATTEMPTS:
            lockout_until = now + self._window_seconds
            self._lockouts[identifier] = lockout_until
            return True, self._window_seconds
        return False, 0

    def is_locked_out(self, identifier: str) -> Tuple[bool, int]:
        if self._redis is not None:
            try:
                key = self._key(identifier)
                count_value = self._redis.get(key)
                count = int(count_value or 0)
                if count >= settings.MAX_LOGIN_ATTEMPTS:
                    ttl = self._redis.ttl(key)
                    return True, max(int(ttl), 1)
                return False, 0
            except RedisError as exc:
                self._redis_unavailable(exc)

        return self._local_is_locked_out(identifier)

    def record_attempt(self, identifier: str, success: bool) -> None:
        if self._redis is not None:
            try:
                key = self._key(identifier)
                if success:
                    self._redis.delete(key)
                else:
                    with self._redis.pipeline(transaction=True) as pipe:
                        pipe.incr(key)
                        pipe.expire(key, self._window_seconds)
                        pipe.execute()
                return
            except RedisError as exc:
                self._redis_unavailable(exc)

        if success:
            self._attempts[identifier] = []
            self._lockouts.pop(identifier, None)
        else:
            self._attempts[identifier].append((time.time(), 1))
            self._clean_old_attempts(identifier)

    def check_rate_limit(self, identifier: str) -> None:
        is_locked, remaining = self.is_locked_out(identifier)
        if is_locked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed login attempts. Please try again later.",
                headers={"Retry-After": str(max(remaining, 1))},
            )


login_rate_limiter = LoginRateLimiter()


def _valid_ip(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _is_trusted_proxy(peer_ip: str | None) -> bool:
    normalized_peer = _valid_ip(peer_ip)
    if not normalized_peer:
        return False
    peer = ipaddress.ip_address(normalized_peer)
    for configured in settings.trusted_proxy_list:
        try:
            if peer in ipaddress.ip_network(configured, strict=False):
                return True
        except ValueError:
            logger.error("Ignoring invalid TRUSTED_PROXY_IPS entry: %s", configured)
    return False


def get_client_identifier(request) -> str:
    """Return a client IP without trusting attacker-supplied proxy headers."""
    peer_ip = request.client.host if request.client else None
    direct_ip = _valid_ip(peer_ip) or "unknown"

    if not _is_trusted_proxy(peer_ip):
        return direct_ip

    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = _valid_ip(forwarded_for.split(",", 1)[0])
        if client_ip:
            return client_ip

    real_ip = _valid_ip(request.headers.get("X-Real-IP"))
    return real_ip or direct_ip


def get_device_identifier(request) -> str:
    """Return a privacy-preserving coarse device identifier for abuse controls."""
    user_agent = request.headers.get("User-Agent", "unknown")[:512]
    accept_language = request.headers.get("Accept-Language", "")[:128]
    digest = hashlib.sha256(f"{user_agent}|{accept_language}".encode("utf-8")).hexdigest()
    return digest
