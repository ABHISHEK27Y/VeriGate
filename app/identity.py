"""Opaque storage identifiers; never put bearer credentials in keys or logs."""

import hashlib
import hmac
from collections.abc import Iterable

from .config import get_settings


def hash_api_key(api_key: str) -> str:
    return hmac.new(
        get_settings().api_key_salt.encode(), api_key.encode(), hashlib.sha256
    ).hexdigest()


def tenant_id(api_key: str) -> str:
    return "t_" + hash_api_key(api_key)


def key_allowed(api_key: str | None, configured: Iterable[str]) -> bool:
    """Compare every configured key without exposing a match position."""
    if not api_key:
        return False
    supplied = api_key.encode("utf-8")
    allowed = False
    for expected in configured:
        matched = hmac.compare_digest(supplied, expected.encode("utf-8"))
        allowed = matched or allowed
    return allowed
