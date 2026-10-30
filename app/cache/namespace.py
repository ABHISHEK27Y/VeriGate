"""Version cache data by every setting that changes answers or matching."""

import hashlib
import json
from pathlib import Path

from ..config import get_settings

POLICY_VERSION = "token-diff-v2"
ANSWER_POLICY_RUNTIME_VERSION = "5"


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
        "answer_policy_artifact",
        "cache_similarity_base",
        "verifier_nli",
        "nli_model",
        "nli_revision",
        "nli_threshold",
        "cache_epoch",
    )
    selected = {key: config[key] for key in fields}
    if artifact := config["answer_policy_artifact"]:
        selected["answer_policy_sha256"] = hashlib.sha256(Path(artifact).read_bytes()).hexdigest()
        selected["answer_policy_runtime_version"] = ANSWER_POLICY_RUNTIME_VERSION
    payload = json.dumps(selected, sort_keys=True)
    digest = hashlib.sha256(("schema-v3:" + POLICY_VERSION + ":" + payload).encode()).hexdigest()[
        :24
    ]
    return f"cache:v3:{digest}"
