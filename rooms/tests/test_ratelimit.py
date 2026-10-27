"""Ограничение частоты попыток входа."""

import pytest
from django.core.cache import cache

from rooms.ratelimit import check_rate_limit, client_ip


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


def test_allows_up_to_limit():
    results = [check_rate_limit("k", limit=3, window=60) for _ in range(3)]

    assert all(r.allowed for r in results)
    assert results[-1].remaining == 0


def test_blocks_above_limit():
    check_rate_limit("k", limit=2, window=60)
    check_rate_limit("k", limit=2, window=60)

    blocked = check_rate_limit("k", limit=2, window=60)

    assert blocked.allowed is False
    assert blocked.retry_after == 60


def test_limits_are_independent_per_key():
    check_rate_limit("a", limit=1, window=60)

    assert check_rate_limit("b", limit=1, window=60).allowed


def test_client_ip_prefers_forwarded_for(rf):
    request = rf.get("/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="203.0.113.5, 10.0.0.1")

    assert client_ip(request) == "203.0.113.5"


def test_client_ip_falls_back_to_remote_addr(rf):
    request = rf.get("/", REMOTE_ADDR="10.0.0.1")

    assert client_ip(request) == "10.0.0.1"
