"""CachePolicy — the single source of truth for the cache decision.

Both the live gateway (semantic_cache.lookup) and the evaluation harness use this, so a
result measured in evaluation is exactly the behaviour that ships. Toggling the flags is
what produces the ablation study (baseline vs +adaptive vs +verifier vs full).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .threshold import adaptive_threshold
from .verifier import NliVerifier, VerifierMode, default_verifier, verify_equivalent

_COSINE_ROUNDING_TOLERANCE = 0.0001


@dataclass
class CachePolicy:
    use_adaptive: bool = True  # Sub-contribution A
    use_verifier: bool = True  # Sub-contribution B (Tier-1 structural checks)
    use_nli: bool = False  # Sub-contribution B (Tier-2 NLI equivalence)
    static_threshold: float = 0.72  # used only when use_adaptive is False
    verifier_mode: VerifierMode = "token_diff"

    verifier: NliVerifier = field(default_factory=default_verifier, repr=False)

    def threshold(self, query: str, density: float = 0.0) -> float:
        if self.use_adaptive:
            return adaptive_threshold(query, density)
        return self.static_threshold

    def decide(
        self, query: str, candidate_query: str, sim: float, density: float = 0.0
    ) -> tuple[bool, str, float]:
        """Return (is_hit, reason, threshold_used) for a candidate nearest match."""
        # A malformed vector score must never turn into a cache hit. In particular,
        # NaN < threshold is False, so the old comparison accepted NaN candidates.
        if not math.isfinite(sim) or abs(sim) > 1.0 + _COSINE_ROUNDING_TOLERANCE:
            return False, "invalid_similarity", self.threshold(query)
        if not math.isfinite(density) or not 0.0 <= density <= 1.0:
            return False, "invalid_density", self.threshold(query)
        t = self.threshold(query, density)
        if not math.isfinite(t) or not 0.0 <= t <= 1.0:
            return False, "invalid_threshold", t
        if sim < t:
            return False, "below_threshold", t
        if self.use_verifier:
            ok, reason = verify_equivalent(
                query,
                candidate_query,
                use_nli=self.use_nli,
                verifier=self.verifier,
                mode=self.verifier_mode,
            )
            if not ok:
                return False, f"verify_rejected:{reason}", t
        return True, "verified_hit" if self.use_verifier else "threshold_hit", t
