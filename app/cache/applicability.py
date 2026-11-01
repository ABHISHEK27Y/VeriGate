"""Experimental evidence-bound suitability checks for a specific cached answer.

Only a single, supported requirement present in both the stored question and
answer is treated as necessary. Unknown language is left to the existing policy.
This checks applicability, not whether the answer is factually correct.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .action_features import extract_actions

Action = Literal["REJECT", "VERIFY"]

_ENVIRONMENTS = {
    "production": "production",
    "prod": "production",
    "staging": "staging",
    "stage": "staging",
    "development": "development",
    "dev": "development",
    "test": "test",
    "qa": "qa",
}
_METHOD = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b")
_VERSION = re.compile(r"\b(?:version|v|TLS)\s*([0-9]+(?:\.[0-9]+)*)\b", re.I)
_MARKER = re.compile(r"\bmarked\s+([a-z][a-z0-9_-]*)\b", re.I)
_PERMISSION = re.compile(r"\b(read-only|read|write|admin)\s+(?:access|permission)\b", re.I)
_YAML_PERMISSION = re.compile(
    r"\bpermissions?\s*:\s*(?:contents\s*:\s*)?(read|write|admin)\b", re.I
)
_NAMED = re.compile(
    r"\b(workspace|namespace|queue|topic|client|server)\s+(?:named\s+)?([a-z][\w.-]*)\b",
    re.I,
)
_WORDS = re.compile(r"\b[a-z]+\b", re.I)
_STOP_VALUES = {"in", "of", "for", "to", "the", "with", "and", "is", "do"}


@dataclass(frozen=True, slots=True)
class Applicability:
    action: Action
    reason: str
    facet: str
    stored_value: str
    incoming_value: str | None


def _facets(text: str) -> dict[str, frozenset[str]]:
    words = [word.casefold() for word in _WORDS.findall(text)]
    actions = extract_actions(text).action_names
    environments = {_ENVIRONMENTS[word] for word in words if word in _ENVIRONMENTS}
    named: dict[str, set[str]] = {}
    for facet, value in _NAMED.findall(text):
        if value.casefold() not in _STOP_VALUES:
            named.setdefault(facet.casefold(), set()).add(value.casefold())
    result = {
        "action": actions,
        "environment": frozenset(environments),
        "http_method": frozenset(value.casefold() for value in _METHOD.findall(text)),
        "version": frozenset(_VERSION.findall(text)),
        "marker": frozenset(value.casefold() for value in _MARKER.findall(text)),
        "permission": frozenset(
            value.casefold().removesuffix("-only")
            for value in (*_PERMISSION.findall(text), *_YAML_PERMISSION.findall(text))
        ),
    }
    result.update({f"named_{key}": frozenset(values) for key, values in named.items()})
    return result


def assess(incoming: str, stored: str, answer: str) -> Applicability | None:
    """Return a supported conflict or necessary missing requirement, else defer to NLI."""
    stored_facets, incoming_facets, answer_facets = (
        _facets(text) for text in (stored, incoming, answer)
    )
    for facet in (
        "http_method",
        "version",
        "named_workspace",
        "named_namespace",
        "named_queue",
        "named_topic",
        "named_client",
        "named_server",
        "marker",
        "permission",
        "environment",
        "action",
    ):
        stored_values = stored_facets.get(facet, frozenset())
        answer_values = answer_facets.get(facet, frozenset())
        # Multiple values in either text do not establish a unique binding.
        if len(stored_values) != 1 or answer_values != stored_values:
            continue
        incoming_values = incoming_facets.get(facet, frozenset())
        if incoming_values == stored_values:
            continue
        stored_value = next(iter(stored_values))
        if len(incoming_values) == 1:
            return Applicability(
                "REJECT",
                f"applicability_{facet}_conflict",
                facet,
                stored_value,
                next(iter(incoming_values)),
            )
        if not incoming_values:
            return Applicability(
                "VERIFY", f"applicability_{facet}_missing", facet, stored_value, None
            )
    return None
