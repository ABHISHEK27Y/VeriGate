"""Query embeddings — pluggable backends.

* "minilm" (default): real *semantic* embeddings via sentence-transformers
  (all-MiniLM-L6-v2, 384-dim). Understands meaning, so "capital of Austria" and
  "capital of Australia" are recognised as DIFFERENT, while "reset my password" and
  "how do I recover my password" are recognised as the SAME. This is what makes the
  semantic cache genuinely semantic.

* "hash": a fast, dependency-free hashing embedder capturing only *lexical* overlap.
  Used in tests (instant, deterministic, no model download) and as a safe fallback if
  sentence-transformers is unavailable.

Selected via get_settings().embedding_backend. The rest of the system is unchanged — it only
calls embed()/cosine().
"""

from __future__ import annotations

import functools
import logging
import re
import threading
import zlib

import numpy as np

from .config import get_settings

log = logging.getLogger("verigate.embeddings")

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _stable_hash(tok: str) -> int:
    # crc32 is deterministic across processes (unlike Python's built-in hash()).
    return zlib.crc32(tok.encode("utf-8"))


def _hash_embed(text: str) -> np.ndarray:
    dim = get_settings().embedding_dim
    vec = np.zeros(dim, dtype=np.float32)
    for tok in tokenize(text):
        vec[_stable_hash(tok) % dim] += 1.0
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


class Embedder:
    """One model per app; loading and inference are serialized off the event loop."""

    def __init__(self):
        self.model = None
        self.backend = get_settings().embedding_backend
        self._lock = threading.Lock()

    def embed(self, text: str) -> np.ndarray:
        if self.backend == "hash":
            return _hash_embed(text)
        with self._lock:
            if self.model is None:
                from sentence_transformers import (  # noqa: PLC0415 - lazy optional model
                    SentenceTransformer,  # noqa: PLC0415 - optional heavy dependency
                )

                self.model = SentenceTransformer(
                    get_settings().embedding_model,
                    revision=get_settings().embedding_revision or None,
                )
            return np.asarray(
                self.model.encode([text], normalize_embeddings=True)[0], dtype=np.float32
            )


@functools.lru_cache(maxsize=1)
def default_embedder() -> Embedder:
    """Standalone evaluation helper. The gateway explicitly creates its own Embedder."""
    return Embedder()


def embed(text: str) -> np.ndarray:
    return default_embedder().embed(text)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


def active_backend() -> str:
    return default_embedder().backend
