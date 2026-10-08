"""The evaluation benchmark: labelled query pairs.

Each pair is (query_a, query_b):
  * POSITIVE  -> the two are semantically equivalent; a cache SHOULD serve a's answer for b.
  * NEGATIVE  -> they look/score similar but have DIFFERENT answers; a cache should NOT
                 (these are the "hard negatives" that cause false hits).

Negatives are grouped by the failure mode they probe (entity swap, number swap, negation,
related-but-different) so the ablation can show which component catches which.

This is a compact, hand-curated seed set for demonstrating the method. For the final
report, expand it (e.g. mine Quora Question Pairs + generate paraphrases) and document the
datasheet — see docs/EVALUATION_PLAN.md.
"""
from __future__ import annotations

# ---- POSITIVES: should be a cache HIT (equivalent meaning) ----
POSITIVES: list[tuple[str, str]] = [
    ("how do I reset my password", "what is the process to recover my account password"),
    ("what is your refund policy", "how do refunds work here"),
    ("how do I cancel my subscription", "what are the steps to unsubscribe"),
    ("do you encrypt user data", "is my data encrypted"),
    ("how do I change my email address", "what is the way to update my email"),
    ("what payment methods do you accept", "which ways can I pay you"),
    ("how do I contact support", "what is the best way to reach customer service"),
    ("how do I delete my account", "what are the steps to remove my profile"),
    ("what is the capital of France", "which city is the capital of France"),
    ("how tall is Mount Everest", "what is the height of Mount Everest"),
    ("who wrote Romeo and Juliet", "which author wrote Romeo and Juliet"),
    ("how do I install python", "what are the steps to set up python"),
    ("what is machine learning", "can you explain what machine learning is"),
    ("how do I enable dark mode", "how can I switch to a dark theme"),
    ("how do I check my order status", "how can I see where my order is"),
]

# ---- NEGATIVES: should NOT be a hit (different answer) ----
NEGATIVES_ENTITY: list[tuple[str, str]] = [
    ("what is the capital of Austria", "what is the capital of Australia"),
    ("what is the capital of France", "what is the capital of Spain"),
    ("how tall is Mount Everest", "how tall is Mount Kilimanjaro"),
    ("who wrote Romeo and Juliet", "who wrote War and Peace"),
    ("what is the population of India", "what is the population of China"),
]

NEGATIVES_NUMBER: list[tuple[str, str]] = [
    ("what is the cost of the 5 GB data plan", "what is the cost of the 50 GB data plan"),
    ("what does the 100 GB plan include", "what does the 500 GB plan include"),
    ("show flights under 200 dollars", "show flights under 2000 dollars"),
]

NEGATIVES_NEGATION: list[tuple[str, str]] = [
    ("is this medicine safe for children", "is this medicine not safe for children"),
    ("is the store open on Sunday", "is the store not open on Sunday"),
]

NEGATIVES_RELATED: list[tuple[str, str]] = [
    ("how do I reset my password", "how do I reset my router"),
    ("how do I cancel my subscription", "how do I renew my subscription"),
    ("what is machine learning", "what is deep learning"),
    ("how do I change my email address", "how do I change my phone number"),
    ("how do I install python", "how do I uninstall python"),
]

NEGATIVES: list[tuple[str, str]] = (
    NEGATIVES_ENTITY + NEGATIVES_NUMBER + NEGATIVES_NEGATION + NEGATIVES_RELATED
)

NEGATIVE_GROUPS = {
    "entity_swap": NEGATIVES_ENTITY,
    "number_swap": NEGATIVES_NUMBER,
    "negation": NEGATIVES_NEGATION,
    "related_topic": NEGATIVES_RELATED,
}

# ---- VOLATILE: answers change over time; must always be BYPASSED (never cached) ----
VOLATILE: list[str] = [
    "what is the weather today",
    "what is the current stock price of Tesla",
    "what is the latest news",
    "what time is it now",
    "what is today's exchange rate for the dollar",
]

# ---- STABLE (non-volatile) controls, to check the staleness detector's false positives ----
STABLE_CONTROLS: list[str] = [
    "what is the capital of France",
    "how do I reset my password",
    "who wrote Romeo and Juliet",
    "how do I install python",
]


def all_unique_queries() -> list[str]:
    """Every distinct query string, so embeddings can be computed once and cached."""
    qs: set[str] = set()
    for a, b in POSITIVES + NEGATIVES:
        qs.add(a)
        qs.add(b)
    qs.update(VOLATILE)
    qs.update(STABLE_CONTROLS)
    return sorted(qs)
