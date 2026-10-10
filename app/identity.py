"""Opaque storage identifiers; never put bearer credentials in keys or logs."""

import hashlib
import hmac

from .config import get_settings


def hash_api_key(api_key: str) -> str:
    return hmac.new(
        get_settings().api_key_salt.encode(), api_key.encode(), hashlib.sha256
    ).hexdigest()


def tenant_id(api_key: str) -> str:
    return "t_" + hash_api_key(api_key)
