"""Guard the heuristic used to explain gold-answer mismatch samples."""

from evaluation.gold_model import _granularity_difference


def test_granularity_flag_is_strict_token_containment() -> None:
    assert _granularity_difference(["1969"], ["July 1969"])
    assert _granularity_difference(["Salt Lake City"], ["Salt Lake City, Utah"])
    assert not _granularity_difference(["Wilt Chamberlain"], ["Chamberlain, Wilt"])
    assert not _granularity_difference(["1969"], ["1970"])
