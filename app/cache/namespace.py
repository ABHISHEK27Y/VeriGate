"""Version cache data by every setting that changes answers or matching."""

import hashlib
import json

from ..config import get_settings


def namespace() -> str:
    config = get_settings().model_dump()
    fields = (
        "embedding_backend",
        "embedding_model",
        "embedding_dim",
        "embedding_revision",
        "llm_provider",
        "openai_base_url",
        "openai_api_key",
        "gemini_api_key",
        "openai_model",
        "openai_strong_model",
        "gemini_base_url",
        "gemini_model",
        "gemini_strong_model",
        "cascade_enabled",
        "cascade_threshold",
        "cache_match_mode",
        "cache_similarity_base",
        "verifier_nli",
        "nli_model",
        "nli_revision",
        "nli_threshold",
        "cache_epoch",
    )
    payload = json.dumps({key: config[key] for key in fields}, sort_keys=True)
    digest = hashlib.sha256(("schema-v3:" + payload).encode()).hexdigest()[:24]
    return f"cache:v3:{digest}"
