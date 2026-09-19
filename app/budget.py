"""Per-key daily spend budget (protects against bill-shock / economic DoS).

Counts PROVIDER calls per API key per UTC day in Redis. Cache hits are free and never counted,
so a good cache hit-rate stretches the budget — a nice property to point out in the report.
Disabled when daily_request_budget <= 0.
"""
from __future__ import annotations

import time

from .config import settings
from .redis_client import get_redis


def _key(api_key: str) -> str:
    day = time.strftime("%Y%m%d", time.gmtime())
    return f"budget:{api_key}:{day}"


def check_and_count(api_key: str) -> bool:
    """Increment today's provider-call count for this key; return False if over budget."""
    if settings.daily_request_budget <= 0:
        return True
    r = get_redis()
    k = _key(api_key)
    n = int(r.incr(k))
    if n == 1:
        r.expire(k, 86400)          # expire the counter after a day
    return n <= settings.daily_request_budget


def used_today(api_key: str) -> int:
    v = get_redis().get(_key(api_key))
    return int(v) if v else 0
