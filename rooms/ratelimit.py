"""Ограничение частоты попыток (rate limit) через кэш Django.

Хранилище — Redis при наличии `REDIS_URL`, иначе локальный кэш процесса.
Этого достаточно для MVP с одним процессом uvicorn и однозначно переключается
на Redis в проде/тестах compose.
"""

from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: int


def client_ip(request) -> str:
    """IP клиента с учётом прокси (Caddy передаёт X-Forwarded-For)."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def check_rate_limit(
    key: str,
    *,
    limit: int,
    window: int,
) -> RateLimitResult:
    """Зарегистрировать попытку и сообщить, не превышен ли лимит.

    Счётчик увеличивается на каждой попытке; окно продлевается при первой.
    """
    count = cache.get(key)
    if count is None:
        cache.set(key, 1, timeout=window)
        return RateLimitResult(allowed=True, remaining=max(limit - 1, 0), retry_after=0)

    count = cache.incr(key)
    if count > limit:
        return RateLimitResult(allowed=False, remaining=0, retry_after=window)
    return RateLimitResult(allowed=True, remaining=max(limit - count, 0), retry_after=0)


def check_join_rate_limit(request) -> RateLimitResult:
    return check_rate_limit(
        f"join-attempt:{client_ip(request)}",
        limit=settings.JOIN_RATE_LIMIT_ATTEMPTS,
        window=settings.JOIN_RATE_LIMIT_WINDOW,
    )
