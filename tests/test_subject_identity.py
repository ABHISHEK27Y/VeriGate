"""The named-work guard blocks false NLI agreement without blocking aliases."""

import csv
import json
from collections import Counter
from pathlib import Path

import pytest

from app.cache.answer_policy import AnswerPolicy
from app.cache.namespace import namespace
from app.cache.subject_identity import conflicting_named_work, named_work
from app.config import Settings, _runtime
from scripts.stress_semantic_http import digest

ARTIFACT = (
    Path(__file__).resolve().parents[1] / "app" / "cache" / "artifacts" / "answer_policy_v1.json"
)
ROOT = Path(__file__).resolve().parents[1]
FRESH = ROOT / "evaluation/runs/subject_guard_holdout_20261030_v2"
FRESH_REQUESTS = 100
AUDIT_ROWS = 54


class AlwaysEntails:
    calls = 0

    def entail_prob(self, _premise: str, _hypothesis: str) -> float:
        self.calls += 1
        return 0.99


@pytest.mark.parametrize(
    ("stored", "incoming"),
    [
        ("Who wrote the song Let It Be?", "Name the writer of the song Let It Go."),
        ("Who wrote the book Dune?", "For the novel Foundation, who wrote it?"),
        ("Who directed the film Arrival?", "Name the director of the movie Gravity."),
        ("Who painted the painting Guernica?", "For the painting The Scream, who painted it?"),
    ],
)
def test_different_named_work_blocks_high_nli(stored: str, incoming: str) -> None:
    verifier = AlwaysEntails()
    decision = AnswerPolicy.load(ARTIFACT).decide(incoming, stored, "Someone", 0.9, verifier)
    assert decision.action == "REJECT"
    assert decision.reason == "subject_identity_conflict"
    assert verifier.calls == 0
    assert conflicting_named_work(incoming, stored)


@pytest.mark.parametrize(
    ("stored", "incoming"),
    [
        ("Who wrote the song Live and Let Die?", "Name the writer of the song live and let die."),
        ("Who wrote the book The Hobbit?", "For the novel Hobbit, who wrote it?"),
        ("Who wrote the novel Moby-Dick?", "Name the writer of the book Moby Dick."),
        ("Who directed the film Arrival?", "For the movie Arrival, who directed it?"),
        ("Who directed the film Arrival?", "For the film Arrival, name its director."),
    ],
)
def test_same_work_wording_and_supported_aliases_reach_nli(stored: str, incoming: str) -> None:
    verifier = AlwaysEntails()
    decision = AnswerPolicy.load(ARTIFACT).decide(incoming, stored, "Someone", 0.9, verifier)
    assert decision.action == "ACCEPT"
    assert verifier.calls == 1
    assert not conflicting_named_work(incoming, stored)


def test_unknown_subject_syntax_does_not_claim_identity() -> None:
    assert named_work("Who wrote Dune?") is None
    assert not conflicting_named_work("Who wrote Dune?", "Who wrote the book Foundation?")


def test_unchanged_policy_can_be_measured_as_baseline() -> None:
    verifier = AlwaysEntails()
    decision = AnswerPolicy.load(ARTIFACT).decide(
        "Who wrote the song Let It Go?",
        "Who wrote the song Let It Be?",
        "Someone",
        0.9,
        verifier,
        subject_guard=False,
    )
    assert decision.action == "ACCEPT"
    assert verifier.calls == 1


def test_guard_mode_changes_cache_namespace() -> None:
    config = Settings(_env_file=None, answer_policy_artifact=str(ARTIFACT))
    token = _runtime.set(config.model_copy(update={"answer_policy_subject_guard": False}))
    try:
        unchanged = namespace()
    finally:
        _runtime.reset(token)
    token = _runtime.set(config.model_copy(update={"answer_policy_subject_guard": True}))
    try:
        guarded = namespace()
    finally:
        _runtime.reset(token)
    assert unchanged != guarded


def test_fresh_four_domain_workload_is_frozen_and_entity_disjoint() -> None:
    freeze = json.loads((FRESH / "freeze.json").read_text(encoding="utf-8"))
    assert digest(FRESH / "workload.csv") == freeze["workload_sha256"]
    assert digest(FRESH / "provider_answers.json") == freeze["provider_answers_sha256"]
    assert digest(ARTIFACT) == freeze["policy_sha256"]
    with (FRESH / "workload.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == freeze["requests"] == FRESH_REQUESTS
    assert len({row["id"] for row in rows}) == FRESH_REQUESTS
    assert len({row["question"] for row in rows}) == FRESH_REQUESTS
    assert Counter(row["domain"] for row in rows) == {
        "song": 32,
        "book": 32,
        "film": 12,
        "poem": 24,
    }
    old_subjects = set()
    for source in (
        ROOT / "evaluation/runs/nq_song_stress_20261030_v3/workload.csv",
        ROOT / "evaluation/runs/subject_guard_holdout_20261030_v1/workload.csv",
    ):
        with source.open(encoding="utf-8", newline="") as stream:
            old_subjects.update(
                named_work(row["question"])
                for row in csv.DictReader(stream)
                if row["kind"] == "original"
            )
    assert all(
        named_work(row["question"]) not in old_subjects for row in rows if row["kind"] == "original"
    )


def test_fresh_http_results_and_failure_audit_are_complete() -> None:
    comparison = json.loads((FRESH / "comparison_manifest.json").read_text(encoding="utf-8"))
    assert digest(FRESH / "comparison.csv") == comparison["comparison_sha256"]
    for mode in ("unchanged", "guarded"):
        directory = FRESH / f"answer_aware_{mode}"
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        assert digest(directory / "requests.csv") == manifest["requests_sha256"]
        assert manifest["config"]["ANSWER_POLICY_SUBJECT_GUARD"] == str(mode == "guarded").lower()
        with (directory / "requests.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == FRESH_REQUESTS
        assert all(row["http_status"] == "200" for row in rows)
    audit = ROOT / "evaluation/analysis/subject_guard_20261030_v1"
    summary = json.loads((audit / "summary.json").read_text(encoding="utf-8"))
    assert digest(audit / "all_54_failure_audit.csv") == summary["audit_sha256"]
    with (audit / "all_54_failure_audit.csv").open(encoding="utf-8", newline="") as stream:
        assert len(list(csv.DictReader(stream))) == summary["rows"] == AUDIT_ROWS
