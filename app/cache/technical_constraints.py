"""Explicit role-bound quantities and scoped polarity for experimental checks.

Only recognized syntax is compared. Missing or unclear bindings abstain; this
does not infer arbitrary numeric or negative meaning from free-form prose.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .action_features import extract_actions

_FIELD = r"retry|retries|timeout|delay|interval|backoff|limit"
_UNIT = r"milliseconds?|ms|seconds?|sec|s|minutes?|min|hours?|h|times|attempts?"
_FORWARD = re.compile(
    rf"\b(?P<field>{_FIELD})\s*(?:of|=|:)?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT})?\b", re.I
)
_REVERSE = re.compile(
    rf"\b(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT})\s*(?P<field>{_FIELD})\b", re.I
)
_NEGATION = re.compile(r"\b(?:not|never|without)\s+(?P<verb>[a-z][a-z-]*)\b", re.I)


@dataclass(frozen=True, slots=True)
class Binding:
    field: str
    value: float
    unit: str
    span: tuple[int, int]


@dataclass(frozen=True, slots=True)
class ConstraintEvidence:
    quantities: tuple[Binding, ...]
    negated_actions: frozenset[str]
    polarity_unknown: bool


def _unit(raw: str | None) -> tuple[str, float]:
    value = (raw or "").casefold()
    if value in {"ms", "millisecond", "milliseconds"}:
        return "time_ms", 1
    if value in {"s", "sec", "second", "seconds"}:
        return "time_ms", 1000
    if value in {"min", "minute", "minutes"}:
        return "time_ms", 60000
    if value in {"h", "hour", "hours"}:
        return "time_ms", 3600000
    if value in {"times", "attempt", "attempts"}:
        return "count", 1
    return "unspecified", 1


def extract_constraints(text: str) -> ConstraintEvidence:
    bindings: list[Binding] = []
    occupied: set[int] = set()
    for pattern in (_FORWARD, _REVERSE):
        for match in pattern.finditer(text):
            if any(index in occupied for index in range(match.start(), match.end())):
                continue
            occupied.update(range(match.start(), match.end()))
            field = match.group("field").casefold()
            field = "retry" if field == "retries" else field
            unit, multiplier = _unit(match.group("unit"))
            bindings.append(
                Binding(field, float(match.group("value")) * multiplier, unit, match.span())
            )
    negated: set[str] = set()
    unknown = False
    for match in _NEGATION.finditer(text):
        action = extract_actions(match.group("verb"))
        if len(action.values) == 1 and not action.unknown:
            negated.update(action.values)
        else:
            unknown = True
    return ConstraintEvidence(tuple(bindings), frozenset(negated), unknown)


def compare_constraints(incoming: str, stored: str) -> str | None:
    left, right = extract_constraints(incoming), extract_constraints(stored)
    if left.polarity_unknown or right.polarity_unknown:
        return "technical_polarity_uncertain"
    if left.negated_actions != right.negated_actions:
        return (
            "technical_polarity_conflict"
            if left.negated_actions and right.negated_actions
            else "technical_polarity_uncertain"
        )
    left_fields = {binding.field for binding in left.quantities}
    right_fields = {binding.field for binding in right.quantities}
    for field in left_fields & right_fields:
        lvalues = Counter(
            (item.value, item.unit) for item in left.quantities if item.field == field
        )
        rvalues = Counter(
            (item.value, item.unit) for item in right.quantities if item.field == field
        )
        if lvalues != rvalues:
            return "technical_quantity_binding_conflict"
    if left_fields != right_fields:
        return "technical_quantity_binding_uncertain"
    return None
