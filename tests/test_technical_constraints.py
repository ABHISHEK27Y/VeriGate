"""Explicit field/quantity and scoped-polarity evidence is conservative."""

from __future__ import annotations

import pytest

from app.cache.technical_constraints import compare_constraints, extract_constraints


@pytest.mark.parametrize(
    ("stored", "incoming", "reason"),
    [
        (
            "Set retries 3 times and timeout 5 seconds.",
            "Set retries 5 times and timeout 3 seconds.",
            "technical_quantity_binding_conflict",
        ),
        (
            "Set timeout 5 seconds.",
            "Set timeout 5 milliseconds.",
            "technical_quantity_binding_conflict",
        ),
        (
            "Use retry 3 times then retry 2 times.",
            "Use retry 3 times.",
            "technical_quantity_binding_conflict",
        ),
        (
            "Do not deploy the app; delete old files.",
            "Deploy the app; do not delete old files.",
            "technical_polarity_conflict",
        ),
        (
            "Do not deploy the app.",
            "Deploy the app.",
            "technical_polarity_uncertain",
        ),
        (
            "Set timeout 5 seconds.",
            "Set the timeout.",
            "technical_quantity_binding_uncertain",
        ),
    ],
)
def test_explicit_bindings(stored: str, incoming: str, reason: str) -> None:
    assert compare_constraints(incoming, stored) == reason


def test_unit_conversion_and_paraphrase_preserve_binding() -> None:
    assert compare_constraints("Set timeout 5000 milliseconds.", "Set timeout 5 seconds.") is None
    assert compare_constraints("Never deploy the app.", "Do not deploy the app.") is None


def test_extractor_retains_quantity_spans() -> None:
    text = "Set retry 3 times and timeout 5 seconds."
    evidence = extract_constraints(text)
    assert len(evidence.quantities) == len(["retry", "timeout"])
    assert [text[item.span[0] : item.span[1]] for item in evidence.quantities] == [
        "retry 3 times",
        "timeout 5 seconds",
    ]
