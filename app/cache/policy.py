"""CachePolicy — the single source of truth for the cache decision.

Both the live gateway (semantic_cache.lookup) and the evaluation harness use this, so a
result measured in evaluation is exactly the behaviour that ships. Toggling the flags is
what produces the ablation study (baseline vs +adaptive vs +verifier vs full).
"""
from __future__ import annotations

from dataclasses import dataclass

from .threshold import adaptive_threshold
from .verifier import verify_equivalent


@dataclass
class CachePolicy:
    use_adaptive: bool = True     # Sub-contribution A
    use_verifier: bool = True     # Sub-contribution B (Tier-1 structural checks)
    use_nli: bool = False         # Sub-contribution B (Tier-2 NLI equivalence)
    static_threshold: float = 0.72  # used only when use_adaptive is False

    def threshold(self, query: str, density: float = 0.0) -> float:
        if self.use_adaptive:
            return adaptive_threshold(query, density)
        return self.static_threshold

    def decide(
        self, query: str, candidate_query: str, sim: float, density: float = 0.0
    ) -> tuple[bool, str, float]:
        """Return (is_hit, reason, threshold_used) for a candidate nearest match."""
        t = self.threshold(query, density)
        if sim < t:
            return False, "below_threshold", t
        if self.use_verifier:
            ok, reason = verify_equivalent(query, candidate_query, use_nli=self.use_nli)
            if not ok:
                return False, f"verify_rejected:{reason}", t
        return True, "verified_hit" if self.use_verifier else "threshold_hit", t
