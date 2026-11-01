"""Compile the report's editable standalone TikZ diagrams without rewriting them.

Run from any directory: python report/figures/build_diagrams.py
Each .tex file is the source of truth. Logs remain beside the PDFs for review.
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIGURES = (
    "use_cases",
    "dfd_context",
    "dfd_level1",
    "request_flow",
    "generation_flow",
    "candidate_decision",
    "hit_sequence",
    "fallback_sequence",
    "organization_scope",
    "storage_design",
    "deployment",
    "startup_readiness",
    "cache_lifecycle",
)


def main() -> int:
    failures = []
    for name in FIGURES:
        source = HERE / f"{name}.tex"
        if not source.is_file():
            failures.append(f"{source.name}: source missing")
            continue
        cmd = [
            "pdflatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            source.name,
        ]
        result = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, check=False)
        log_path = HERE / f"{name}.log"
        if result.returncode:
            failures.append(f"{source.name}: pdflatex failed ({result.returncode}); see {log_path}")
            print(result.stdout[-3000:], file=sys.stderr)
            print(result.stderr[-1000:], file=sys.stderr)
        else:
            print(f"{source.name} -> {name}.pdf (log: {log_path.name})")
    if failures:
        print("\n".join(failures), file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
