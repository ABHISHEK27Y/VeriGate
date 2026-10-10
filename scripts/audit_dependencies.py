"""Audit installed distributions, mapping CPU Torch to its upstream release version."""

from __future__ import annotations

import importlib.metadata
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    requirements = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"]
        if name.lower() == "verigate":
            continue  # local project: reviewed in source, not a published dependency
        version = distribution.version
        if name.lower() == "torch" and version.endswith("+cpu"):
            version = version.removesuffix("+cpu")
        requirements.append(f"{name}=={version}")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "installed.txt"
        path.write_text("\n".join(sorted(requirements)), encoding="utf-8")
        return subprocess.call(
            [
                sys.executable,
                "-m",
                "pip_audit",
                "--strict",
                "--desc",
                "--no-deps",
                "--disable-pip",
                "-r",
                str(path),
                *sys.argv[1:],
            ]
        )


if __name__ == "__main__":
    raise SystemExit(main())
