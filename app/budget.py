"""Daily admitted miss/bypass request limit, per key and UTC day.

Retries and cascade attempts may make multiple upstream calls per admission.
This is not a token, provider-attempt, or monetary spending cap.
"""

from __future__ import annotations

import time

from redis.exceptions import WatchError

from .config import get_settings
from .identity import hash_api_key


def _key(api_key: str) -> str:
    day = time.strftime("%Y%m%d", time.gmtime())
    return f"budget:{hash_api_key(api_key)}:{day}"


async def check_and_count(api_key: str, r) -> bool:
    """Increment today's admitted-request count for this key; return False if over budget."""
    if get_settings().daily_request_budget <= 0:
        return True
    k = _key(api_key)
    for _ in range(100):
        try:
            async with r.pipeline(transaction=True) as pipe:
                await pipe.watch(k)
                n = int(await pipe.get(k) or 0)
                if n >= get_settings().daily_request_budget:
                    return False
                pipe.multi()
                pipe.incr(k)
                pipe.expire(k, 86400)
                await pipe.execute()
                return True
        except WatchError:
            continue
    return False  # fail closed under sustained contention


async def used_today(api_key: str, r) -> int:
    v = await r.get(_key(api_key))
    return int(v) if v else 0
