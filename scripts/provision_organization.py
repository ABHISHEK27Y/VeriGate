"""Create a local hashed-key organization directory or rotate/revoke a key.

Pass gateway keys through environment variables, never command-line arguments.
The output contains HMAC digests, no gateway or provider secrets.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.config import Settings, _runtime
from app.identity import hash_api_key

_MIN_KEY_CHARS = 16


def _digest(variable: str) -> str:
    key = os.environ.get(variable, "")
    if len(key) < _MIN_KEY_CHARS:
        raise ValueError(f"{variable} must contain a gateway key of at least 16 characters")
    return hash_api_key(key)


def _write(path: Path, directory: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(directory, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def init_demo(path: Path) -> None:
    if path.exists():
        raise FileExistsError(path)
    if os.environ.get("ENVIRONMENT", "development") != "development":
        raise ValueError("The seeded organization demo is development-only")
    directory = {
        "schema_version": 1,
        "organizations": {
            "example": {
                "default_profile": "example-mock",
                "application_defaults": {"developer-tool": "engineering"},
                "workspaces": {
                    "engineering": {
                        "members": ["alice", "carol"],
                        "trusted_applications": ["developer-tool"],
                    }
                },
            },
            "other": {"default_profile": "other-mock", "workspaces": {}},
        },
        "provider_profiles": {
            "example-mock": {"provider": "mock"},
            "other-mock": {"provider": "mock"},
        },
        "credentials": [
            {
                "key_digest": hash_api_key(key),
                "organization_id": org,
                "subject_id": subject,
                "application_id": "developer-tool",
                "permissions": ["cache:shared"] if org == "example" else [],
                "status": "active",
            }
            for key, org, subject in (
                ("example-alice-key-12345", "example", "alice"),
                ("example-carol-key-12345", "example", "carol"),
                ("other-dave-key-123456", "other", "dave"),
            )
        ],
    }
    _write(path, directory)


def ensure_demo_default(path: Path) -> None:
    """Migrate only the known public mock demo directory, without touching cache data."""
    if (
        path.name != "organizations-demo.json"
        or os.environ.get("ENVIRONMENT", "development") != "development"
    ):
        raise ValueError("Only the local development demo directory may be migrated")
    directory = json.loads(path.read_text(encoding="utf-8"))
    org = directory["organizations"]["example"]
    workspace = org["workspaces"]["engineering"]
    if (
        directory.get("schema_version") != 1
        or directory["provider_profiles"]["example-mock"]["provider"] != "mock"
        or sorted(workspace["members"]) != ["alice", "carol"]
        or "developer-tool" not in workspace["trusted_applications"]
        or org.get("application_defaults", {}).get("developer-tool") not in {None, "engineering"}
    ):
        raise ValueError("Existing directory is not the expected mock demo; leave it unchanged")
    if org.get("application_defaults", {}).get("developer-tool") == "engineering":
        return
    org.setdefault("application_defaults", {})["developer-tool"] = "engineering"
    _write(path, directory)


def rotate(path: Path) -> None:
    directory = json.loads(path.read_text(encoding="utf-8"))
    old, new = _digest("VERIGATE_OLD_GATEWAY_KEY"), _digest("VERIGATE_NEW_GATEWAY_KEY")
    if old == new or any(row["key_digest"] == new for row in directory["credentials"]):
        raise ValueError("New gateway key must be distinct and unused")
    matches = [row for row in directory["credentials"] if row["key_digest"] == old]
    if len(matches) != 1 or matches[0].get("status", "active") != "active":
        raise ValueError("Old gateway key is not active")
    replacement = {**matches[0], "key_digest": new, "status": "active"}
    matches[0]["status"] = "revoked"
    directory["credentials"].append(replacement)
    _write(path, directory)


def revoke(path: Path) -> None:
    directory = json.loads(path.read_text(encoding="utf-8"))
    digest = _digest("VERIGATE_OLD_GATEWAY_KEY")
    matches = [row for row in directory["credentials"] if row["key_digest"] == digest]
    if len(matches) != 1:
        raise ValueError("Gateway key not found")
    matches[0]["status"] = "revoked"
    _write(path, directory)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("init-demo", "ensure-demo-default", "rotate", "revoke"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    token = _runtime.set(Settings())
    try:
        if args.action == "init-demo":
            init_demo(args.path)
        elif args.action == "ensure-demo-default":
            ensure_demo_default(args.path)
        elif args.action == "rotate":
            rotate(args.path)
        else:
            revoke(args.path)
    finally:
        _runtime.reset(token)


if __name__ == "__main__":
    main()
