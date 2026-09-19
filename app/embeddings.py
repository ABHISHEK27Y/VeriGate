"""Query embeddings — pluggable backends.

* "minilm" (default): real *semantic* embeddings via sentence-transformers
  (all-MiniLM-L6-v2, 384-dim). Understands meaning, so "capital of Austria" and
  "capital of Australia" are recognised as DIFFERENT, while "reset my password" and
  "how do I recover my password" are recognised as the SAME. This is what makes the
  semantic cache genuinely semantic.

* "hash": a fast, dependency-free hashing embedder capturing only *lexical* overlap.
  Used in tests (instant, deterministic, no model download) and as a safe fallback if
  sentence-transformers is unavailable.

Selected via settings.embedding_backend. The rest of the system is unchanged — it only
calls embed()/cosine().
"""
from __future__ import annotations

import logging
import re
import zlib

import numpy as np

from .config import settings

log = logging.getLogger("verigate.embeddings")

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_model = None          # lazily-loaded SentenceTransformer
_active_backend = None  # resolved on first use


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _stable_hash(tok: str) -> int:
    # crc32 is deterministic across processes (unlike Python's built-in hash()).
    return zlib.crc32(tok.encode("utf-8"))


def _hash_embed(text: str) -> np.ndarray:
    dim = settings.embedding_dim
    vec = np.zeros(dim, dtype=np.float32)
    for tok in tokenize(text):
        vec[_stable_hash(tok) % dim] += 1.0
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


def _load_minilm():
    """Load the model once; fall back to the hash backend if unavailable."""
    global _model, _active_backend
    try:
        from sentence_transformers import SentenceTransformer

        log.info("Loading embedding model %s ...", settings.embedding_model)
        _model = SentenceTransformer(settings.embedding_model)
        _active_backend = "minilm"
    except Exception as e:  # noqa: BLE001 - any import/download failure -> fallback
        log.warning("Could not load '%s' (%s); falling back to hash embedder.",
                    settings.embedding_model, e)
        _active_backend = "hash"


def _resolve_backend() -> str:
    global _active_backend
    if _active_backend is not None:
        return _active_backend
    if settings.embedding_backend == "minilm":
        _load_minilm()
    else:
        _active_backend = "hash"
    return _active_backend


def embed(text: str) -> np.ndarray:
    if _resolve_backend() == "minilm":
        return _model.encode([text], normalize_embeddings=True)[0].astype(np.float32)
    return _hash_embed(text)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    # both backends return L2-normalized vectors, so dot == cosine similarity
    return float(np.dot(a, b))


def active_backend() -> str:
    return _resolve_backend()
