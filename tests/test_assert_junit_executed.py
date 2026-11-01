"""The opt-in regression guard must fail on silent skips, not just on failures."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.assert_junit_executed import main, summarize

RAN = '<testsuite tests="3" failures="0" errors="0" skipped="0"></testsuite>'
SKIPPED = '<testsuite tests="3" failures="0" errors="0" skipped="3"></testsuite>'
FAILED = '<testsuite tests="3" failures="1" errors="0" skipped="0"></testsuite>'


def _write(tmp_path: Path, xml: str) -> Path:
    path = tmp_path / "out.xml"
    path.write_text(xml, encoding="utf-8")
    return path


def test_passes_when_required_tests_execute(tmp_path: Path) -> None:
    assert main([str(_write(tmp_path, RAN)), "--min-passed", "3"]) == 0  # type: ignore[arg-type]


def test_fails_when_every_test_is_silently_skipped(tmp_path: Path) -> None:
    assert main([str(_write(tmp_path, SKIPPED)), "--min-passed", "1"]) == 1  # type: ignore[arg-type]


def test_fails_when_a_test_fails(tmp_path: Path) -> None:
    assert main([str(_write(tmp_path, FAILED)), "--min-passed", "1"]) == 1  # type: ignore[arg-type]


def test_fails_when_fewer_than_expected_passed(tmp_path: Path) -> None:
    assert main([str(_write(tmp_path, RAN)), "--min-passed", "5"]) == 1  # type: ignore[arg-type]


def test_summarize_rejects_empty_report(tmp_path: Path) -> None:
    path = tmp_path / "empty.xml"
    path.write_text("<testsuites></testsuites>", encoding="utf-8")
    with pytest.raises(ValueError, match="No pytest test suites"):
        summarize(path)
