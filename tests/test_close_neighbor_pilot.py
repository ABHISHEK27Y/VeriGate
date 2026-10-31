"""Close-neighbor selection keeps proxy labels directional and questions disjoint."""

import numpy as np

from scripts.run_close_neighbor_pilot import _candidate_pairs


def test_directional_pair_selection_is_balanced_and_disjoint() -> None:
    rows = [
        {"line": 1, "query": "Who wrote Alpha?", "answers": ["Writer A"]},
        {"line": 2, "query": "Name the author of Alpha", "answers": ["Writer A"]},
        {"line": 3, "query": "Who wrote Beta?", "answers": ["Writer B"]},
        {"line": 4, "query": "Who wrote Gamma?", "answers": ["Writer C"]},
    ]
    vectors = np.tile(np.array([[1.0, 0.0]], dtype=np.float32), (len(rows), 1))
    freeze = {
        "minimum_minilm_cosine": 0.7,
        "selection_seed": "test",
        "proxy_positive_pairs": 1,
        "proxy_negative_pairs": 1,
    }
    pairs = _candidate_pairs(rows, vectors, freeze)
    assert len(pairs) == len(rows) // 2
    assert {pair["proxy_reference_match"] for pair in pairs} == {True, False}
    lines = [line for pair in pairs for line in (pair["cached_line"], pair["incoming_line"])]
    assert len(lines) == len(set(lines))
