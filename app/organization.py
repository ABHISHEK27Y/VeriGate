"""Server-owned organization identities, cache scopes, and provider profiles.

The directory stores only HMAC digests of gateway credentials. A legacy key
continues to use its old private tenant; it is never promoted into an org scope.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .identity import key_allowed

_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_ACTUAL_SECRET = re.compile(
    r"\b(?:sk-[a-zA-Z0-9]{12,}|AKIA[A-Z0-9]{16})\b|"
    r"\b(?:password|api[_ -]?key|access[_ -]?token|secret)\s*[:=]\s*\S+",
    re.IGNORECASE,
)
_PRIVATE_CONTEXT = re.compile(
    r"\b(?:my|mine|our)\s+(?:\w+\s+){0,3}"
    r"(?:account|customer|patient|salary|employee|internal|private|password|credential)\b|"
    r"\b[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Principal:
    organization_id: str
    subject_id: str
    application_id: str
    permissions: frozenset[str]
    workspaces: frozenset[str]
    provider_profile: str
    status: str
    legacy_tenant: str | None = None
    default_workspace: str | None = None

    @property
    def legacy(self) -> bool:
        return self.legacy_tenant is not None


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    profile_id: str
    provider: str
    model: str
    base_url: str
    secret_env: str


@dataclass(frozen=True, slots=True)
class ScopeDecision:
    scope: str
    workspace: str
    eligibility: str
    reason: str
    policy_version: str


def content_eligibility(text: str) -> str:
    """Conservative storage class; this is not a comprehensive DLP system."""
    if _ACTUAL_SECRET.search(text):
        return "no_store"
    if _PRIVATE_CONTEXT.search(text):
        return "private_only"
    return "shared_eligible"


class OrganizationDirectory:
    def __init__(self, config: Settings) -> None:
        self.config = config
        self.path = (
            Path(config.organization_config_path) if config.organization_config_path else None
        )
        self.file_version: tuple[int, int] | None = None
        self.credentials: dict[str, Principal] = {}
        self.profiles: dict[str, ProviderProfile] = {}
        self.profile_compatibility: dict[str, str] = {}
        self.organizations: dict[str, dict] = {}
        if self.path:
            self._load(self.path)
            stat = self.path.stat()
            self.file_version = stat.st_mtime_ns, stat.st_size

    def _refresh_credentials(self) -> None:
        if self.path is None:
            return
        stat = self.path.stat()
        version = stat.st_mtime_ns, stat.st_size
        if version == self.file_version:
            return
        updated = OrganizationDirectory(self.config)
        if updated.file_version != version:
            raise ValueError("Credential directory changed during reload; retry request")
        if (
            updated.profiles != self.profiles
            or updated.organizations != self.organizations
            or updated.profile_compatibility != self.profile_compatibility
        ):
            raise ValueError("Provider or workspace changes require gateway restart")
        self.credentials = updated.credentials
        self.file_version = version

    def _load(self, path: Path) -> None:  # noqa: PLR0912 - directory schema checks
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != 1:
            raise ValueError("Unsupported organization directory schema")
        for org_id, org in raw.get("organizations", {}).items():
            self._identifier(org_id)
            self._identifier(org["default_profile"])
            for workspace_id, workspace in org.get("workspaces", {}).items():
                self._identifier(workspace_id)
                if not isinstance(workspace.get("members", []), list) or not isinstance(
                    workspace.get("trusted_applications", []), list
                ):
                    raise TypeError("Workspace membership must be configured server-side")
            for application_id, workspace_id in org.get("application_defaults", {}).items():
                self._identifier(application_id)
                if workspace_id not in org.get("workspaces", {}):
                    raise ValueError("Application default references unknown workspace")
            self.organizations[org_id] = org
        for profile_id, profile in raw.get("provider_profiles", {}).items():
            self._identifier(profile_id)
            provider = profile["provider"]
            if provider not in {"mock", "openai", "gemini"}:
                raise ValueError("Unsupported organization provider profile")
            if provider == "mock" and self.config.environment != "development":
                raise ValueError("Mock organization provider requires development mode")
            secret_env = profile.get("secret_env", "")
            if provider != "mock" and (
                not secret_env or not re.fullmatch(r"[A-Z][A-Z0-9_]*", secret_env)
            ):
                raise ValueError("Real provider profile requires an environment secret reference")
            if "api_key" in profile or "secret" in profile:
                raise ValueError("Provider secrets must not be stored in the directory")
            self.profiles[profile_id] = ProviderProfile(
                profile_id,
                provider,
                profile.get("model", ""),
                profile.get("base_url", ""),
                secret_env,
            )
            compatibility = {
                "provider": provider,
                "model": self.profiles[profile_id].model,
                "base_url": self.profiles[profile_id].base_url,
                "secret_env": secret_env,
                "secret_digest": (
                    hmac.new(
                        self.config.api_key_salt.encode(),
                        os.environ.get(secret_env, "").encode(),
                        hashlib.sha256,
                    ).hexdigest()
                    if secret_env
                    else ""
                ),
            }
            self.profile_compatibility[profile_id] = hashlib.sha256(
                json.dumps(compatibility, sort_keys=True).encode()
            ).hexdigest()
        for row in raw.get("credentials", []):
            digest = row["key_digest"]
            if not re.fullmatch(r"[a-f0-9]{64}", digest) or digest in self.credentials:
                raise ValueError("Invalid or repeated gateway key digest")
            org_id, subject_id, application_id = (
                row["organization_id"],
                row["subject_id"],
                row["application_id"],
            )
            for value in (org_id, subject_id, application_id):
                self._identifier(value)
            org = self.organizations.get(org_id)
            if not org:
                raise ValueError("Credential references unknown organization")
            profile = row.get("provider_profile") or org["default_profile"]
            if profile not in self.profiles:
                raise ValueError("Credential references unknown provider profile")
            status = row.get("status", "active")
            if status not in {"active", "revoked"}:
                raise ValueError("Invalid credential status")
            workspaces = frozenset(
                name
                for name, workspace in org.get("workspaces", {}).items()
                if subject_id in workspace["members"]
                and application_id in workspace["trusted_applications"]
            )
            default_workspace = org.get("application_defaults", {}).get(application_id)
            if default_workspace not in workspaces:
                default_workspace = None
            principal = Principal(
                org_id,
                subject_id,
                application_id,
                frozenset(row.get("permissions", [])),
                workspaces,
                profile,
                status,
                default_workspace=default_workspace,
            )
            # Two active credentials may represent one stable employee during rotation.
            self.credentials[digest] = principal

    @staticmethod
    def _identifier(value: str) -> None:
        if not isinstance(value, str) or not _ID.fullmatch(value):
            raise ValueError("Organization identifiers must be simple stable labels")

    def resolve(self, api_key: str | None) -> Principal | None:
        if not api_key:
            return None
        self._refresh_credentials()
        digest = hmac.new(
            self.config.api_key_salt.encode(), api_key.encode(), hashlib.sha256
        ).hexdigest()
        match = None
        for expected, principal in self.credentials.items():
            if hmac.compare_digest(digest, expected):
                match = principal
        if match is not None:
            return match if match.status == "active" else None
        if key_allowed(api_key, self.config.api_key_set):
            return Principal(
                "legacy",
                "t_" + digest,
                "legacy",
                frozenset(),
                frozenset(),
                "legacy",
                "active",
                "t_" + digest,
            )
        return None

    def profile_secret(self, profile_id: str) -> str:
        profile = self.profiles[profile_id]
        if profile.provider == "mock":
            return ""
        secret = os.environ.get(profile.secret_env, "")
        if not secret:
            raise ValueError(f"Provider profile {profile_id} lacks its configured server secret")
        return secret

    def scoped_tenant(self, principal: Principal, scope: str, workspace: str, route: str) -> str:
        if principal.legacy_tenant is not None:
            return f"{principal.legacy_tenant}:{route}" if route else principal.legacy_tenant
        if scope == "workspace":
            identity = f"{principal.organization_id}:workspace:{workspace}"
            prefix = "s"
        else:
            identity = f"{principal.organization_id}:private:{principal.subject_id}"
            prefix = "p"
        # The provider profile and actual route are part of answer compatibility.
        identity += (
            f":{principal.provider_profile}:"
            f"{self.profile_compatibility[principal.provider_profile]}:{route}"
        )
        opaque = hmac.new(
            self.config.api_key_salt.encode(), identity.encode(), hashlib.sha256
        ).hexdigest()
        organization = hmac.new(
            self.config.api_key_salt.encode(),
            principal.organization_id.encode(),
            hashlib.sha256,
        ).hexdigest()[:16]
        return f"{prefix}_{organization}_{opaque}"

    def effective_scope(
        self, principal: Principal, requested: str | None, workspace: str | None, prompt: str
    ) -> tuple[str, str]:
        decision = self.scope_decision(principal, requested, workspace, prompt)
        return decision.scope, decision.workspace

    def scope_decision(  # noqa: PLR0911 - explicit authorization outcomes
        self, principal: Principal, requested: str | None, workspace: str | None, prompt: str
    ) -> ScopeDecision:
        version = hashlib.sha256(
            json.dumps(
                self.organizations.get(principal.organization_id, {}), sort_keys=True
            ).encode()
        ).hexdigest()[:12]
        eligibility = content_eligibility(prompt)
        if requested == "none" or eligibility == "no_store":
            return ScopeDecision("private", "", "no_store", "sensitive_or_disabled", version)
        if principal.legacy:
            return ScopeDecision("private", "", "private_only", "legacy_private", version)
        if requested == "private":
            return ScopeDecision("private", "", "private_only", "explicit_private", version)
        selected = workspace if requested == "workspace" else principal.default_workspace
        if selected is None:
            return ScopeDecision("private", "", "private_only", "no_default_workspace", version)
        if selected not in principal.workspaces or "cache:shared" not in principal.permissions:
            if requested is None:
                return ScopeDecision(
                    "private", "", "private_only", "shared_not_authorized", version
                )
            raise PermissionError("Workspace cache access not authorized")
        if eligibility == "private_only":
            return ScopeDecision("private", "", "private_only", "private_context", version)
        return ScopeDecision(
            "workspace",
            selected,
            "shared_eligible",
            "authorized_default" if requested is None else "authorized_explicit",
            version,
        )


def response_shareable(answer: str) -> bool:
    """Detection can only restrict an authorized shared write, never grant one."""
    return content_eligibility(answer) == "shared_eligible"
