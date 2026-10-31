"""Conservative technical identity features before answer-level NLI.

These are deliberately bounded syntax features, not universal entity linking.
Missing or multi-product extraction abstains instead of asserting equivalence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..embeddings import tokenize

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
_ACTIONS = {
    "create": "create",
    "add": "create",
    "delete": "delete",
    "remove": "delete",
    "drop": "delete",
    "update": "update",
    "change": "update",
    "modify": "update",
    "read": "read",
    "get": "read",
    "fetch": "read",
    "enable": "enable",
    "activate": "enable",
    "disable": "disable",
    "deactivate": "disable",
    "install": "install",
    "setup": "install",
    "deploy": "deploy",
    "release": "deploy",
    "rollback": "rollback",
    "revert": "rollback",
    "backup": "backup",
    "backups": "backup",
    "restore": "restore",
    "recover": "restore",
    "restart": "restart",
    "reboot": "restart",
    "start": "start",
    "stop": "stop",
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
_CODE_ID = re.compile(r"`([^`]{1,80})`|\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b|--[a-z][\w-]+")


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

    @property
    def relevant(self) -> bool:
        return bool(self.products or self.identifiers)


def extract(question: str) -> TechnicalIdentity:
    text = question.replace("Node.js", "nodejs").replace("node.js", "nodejs")
    words = tokenize(text)
    # A bare "node" is common prose; only treat Node.js/nodejs as the product.
    products = frozenset(
        _PRODUCT_ALIASES[word]
        for word in words
        if word in _PRODUCT_ALIASES and (word != "node" or "node.js" in question.casefold())
    )
    identifiers = frozenset(
        re.sub(r"\s+", "", match.group(0).strip("` ")).casefold()
        for match in _CODE_ID.finditer(question)
    )
    actions = frozenset(_ACTIONS[word] for word in words if word in _ACTIONS)
    # "Make a backup" and "make a branch" are generic auxiliaries; the
    # explicit operation supplies the relation when one is present.
    if "make" in words and not actions:
        actions = frozenset({"create"})
    return TechnicalIdentity(
        products,
        actions,
        frozenset(_ENVIRONMENTS[word] for word in words if word in _ENVIRONMENTS),
        frozenset(_CONSTRAINTS[word] for word in words if word in _CONSTRAINTS),
        identifiers,
    )


def compare(incoming: str, stored: str) -> str | None:
    """Return conflict/uncertainty reason, or None when NLI may assess reuse."""
    left, right = extract(incoming), extract(stored)
    if not left.relevant and not right.relevant:
        return None
    if not left.relevant or not right.relevant:
        return "technical_identity_uncertain"
    if len(left.products) > 1 or len(right.products) > 1:
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
