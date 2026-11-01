"""Conservative technical identity features before answer-level NLI.

These are deliberately bounded syntax features, not universal entity linking.
Missing or multi-product extraction abstains instead of asserting equivalence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..embeddings import tokenize
from .action_features import ActionEvidence, extract_actions
from .technical_constraints import compare_constraints

_PRODUCT_ALIASES = {
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "k8s": "kubernetes",
    "kubernetes": "kubernetes",
    "nodejs": "nodejs",
    "node": "nodejs",
    "redis": "redis",
    "mysql": "mysql",
    "docker": "docker",
    "python": "python",
    "nginx": "nginx",
    "fastapi": "fastapi",
    "s3": "s3",
    "git": "git",
    "linux": "linux",
}
_ENVIRONMENTS = {
    "production": "production",
    "prod": "production",
    "staging": "staging",
    "stage": "staging",
    "development": "development",
    "dev": "development",
    "local": "development",
}
_CONSTRAINTS = {
    "async": "async",
    "asynchronous": "async",
    "sync": "sync",
    "synchronous": "sync",
    "public": "public",
    "private": "private",
    "before": "before",
    "after": "after",
}
_CODE_ID = re.compile(
    r"`([^`]{1,80})`|\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b|--[A-Za-z][\w-]+|"
    r"(?<!\w)(?:[A-Za-z]:\\|/)[^\s`'\"?]+|\"([^\"\n]{1,80})\"|'([^'\n]{1,80})'"
)


def normalized_for_numbers(question: str) -> str:
    """Keep a supported product alias from looking like a changed quantity."""
    return re.sub(r"\bk8s\b", "kubernetes", question, flags=re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class TechnicalIdentity:
    products: frozenset[str]
    actions: frozenset[str]
    environments: frozenset[str]
    constraints: frozenset[str]
    identifiers: frozenset[str]
    opaque_identifiers: frozenset[str] = frozenset()
    action_unknown: bool = False
    action_evidence: tuple[ActionEvidence, ...] = ()

    @property
    def relevant(self) -> bool:
        return bool(self.products or self.identifiers or self.opaque_identifiers)


def extract(question: str) -> TechnicalIdentity:
    text = question.replace("Node.js", "nodejs").replace("node.js", "nodejs")
    words = tokenize(text)
    # A bare "node" is common prose; only treat Node.js/nodejs as the product.
    products = frozenset(
        _PRODUCT_ALIASES[word]
        for word in words
        if word in _PRODUCT_ALIASES and (word != "node" or "node.js" in question.casefold())
    )
    identifiers: set[str] = set()
    opaque: set[str] = set()
    for match in _CODE_ID.finditer(question):
        token = match.group(0)
        if token.startswith("`"):
            content = token[1:-1]
            (opaque if any(char.isspace() for char in content) else identifiers).add(content)
        elif token.startswith(('"', "'")):
            opaque.add(token[1:-1])
        else:
            identifiers.add(token)
    actions = extract_actions(question)
    return TechnicalIdentity(
        products,
        actions.action_names,
        frozenset(_ENVIRONMENTS[word] for word in words if word in _ENVIRONMENTS),
        frozenset(_CONSTRAINTS[word] for word in words if word in _CONSTRAINTS),
        frozenset(identifiers),
        frozenset(opaque),
        actions.unknown,
        actions.evidence,
    )


def compare(incoming: str, stored: str) -> str | None:  # noqa: PLR0911
    """Return conflict/uncertainty reason, or None when NLI may assess reuse."""
    if constraint_reason := compare_constraints(incoming, stored):
        return constraint_reason
    left, right = extract(incoming), extract(stored)
    if not left.relevant and not right.relevant:
        return None
    if not left.relevant or not right.relevant:
        return "technical_identity_uncertain"
    if len(left.products) > 1 or len(right.products) > 1:
        return "technical_identity_uncertain"
    if left.action_unknown or right.action_unknown:
        return "technical_identity_uncertain"
    if left.opaque_identifiers != right.opaque_identifiers:
        return "technical_identity_uncertain"
    for name, a, b in (
        ("product", left.products, right.products),
        ("action", left.actions, right.actions),
        ("environment", left.environments, right.environments),
        ("constraint", left.constraints, right.constraints),
        ("identifier", left.identifiers, right.identifiers),
    ):
        if a and b and a != b:
            return f"technical_{name}_conflict"
        if name in {"product", "environment", "identifier"} and bool(a) != bool(b):
            return "technical_identity_uncertain"
    return None
