"""Version cache data by every setting that changes answers or matching."""

import hashlib
import json
from pathlib import Path

from ..config import RuntimeSettings, get_settings

POLICY_VERSION = "token-diff-v2"
ANSWER_POLICY_RUNTIME_VERSION = "8"


def namespace() -> str:
    runtime = get_settings()
    if isinstance(runtime, RuntimeSettings) and runtime._namespace_snapshot is not None:
        return runtime._namespace_snapshot
    config = runtime.model_dump()
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
    selected["scoped_storage_schema"] = 2
    if config["cache_policy_static"]:
        selected["cache_policy_static"] = True
    if artifact := config["answer_policy_artifact"]:
        selected["answer_policy_sha256"] = (
            runtime._answer_policy_sha256
            if isinstance(runtime, RuntimeSettings) and runtime._answer_policy_sha256
            else hashlib.sha256(Path(artifact).read_bytes()).hexdigest()
        )
        selected["answer_policy_runtime_version"] = ANSWER_POLICY_RUNTIME_VERSION
        selected["answer_policy_subject_guard"] = config["answer_policy_subject_guard"]
        selected["answer_policy_technical_guard"] = config["answer_policy_technical_guard"]
    payload = json.dumps(selected, sort_keys=True)
    digest = hashlib.sha256(("schema-v3:" + POLICY_VERSION + ":" + payload).encode()).hexdigest()[
        :24
    ]
    result = f"cache:v3:{digest}"
    if isinstance(runtime, RuntimeSettings) and (
        not artifact or runtime._answer_policy_sha256 is not None
    ):
        runtime._namespace_snapshot = result
    return result
