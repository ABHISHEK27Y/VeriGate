"""Bounded action evidence shared by experimental technical guards.

This normalizes supported verb forms, retaining the source span. An unresolved
"remove" target stays unknown; matching actions alone never authorizes reuse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_WORD = re.compile(r"\b[a-z][a-z-]*\b", re.I)
_ALIASES = {
    "plan": "plan",
    "preview": "plan",
    "apply": "apply",
    "backup": "backup",
    "restore": "restore",
    "recover": "restore",
    "rollback": "rollback",
    "revert": "rollback",
    "grant": "grant",
    "give": "grant",
    "revoke": "revoke",
    "enable": "enable",
    "activate": "enable",
    "disable": "disable",
    "deactivate": "disable",
    "delete": "delete",
    "drop": "delete",
    "create": "create",
    "add": "create",
    "deploy": "deploy",
    "release": "deploy",
    "restart": "restart",
    "reboot": "restart",
    "run": "run",
    "execute": "run",
    "update": "update",
    "change": "update",
    "modify": "update",
    "read": "read",
    "get": "read",
    "fetch": "read",
    "install": "install",
    "setup": "install",
    "start": "start",
    "stop": "stop",
}
_IRREGULAR = {
    "gave": "give",
    "given": "give",
    "applied": "apply",
    "applying": "apply",
    "ran": "run",
    "made": "make",
}
_PERMISSION_TARGETS = {
    "access",
    "permission",
    "permissions",
    "privilege",
    "privileges",
    "role",
    "roles",
}
_RESOURCE_TARGETS = {"key", "topic", "file", "namespace", "table", "resource", "record", "object"}
_BACKUP = re.compile(r"\bback(?:ed|ing)?\s+up\b", re.I)


@dataclass(frozen=True, slots=True)
class ActionEvidence:
    value: str
    surface: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class ActionExtraction:
    evidence: tuple[ActionEvidence, ...]
    unknown: bool = False

    @property
    def values(self) -> frozenset[str]:
        return frozenset(item.value for item in self.evidence)


def _lemma(word: str) -> str | None:
    lower = word.casefold()
    if lower in _IRREGULAR:
        return _IRREGULAR[lower]
    if lower in _ALIASES or lower in {"remove", "make"}:
        return lower
    forms: list[str] = []
    if lower.endswith("ing"):
        forms.extend((lower[:-3], lower[:-3] + "e"))
    if lower.endswith("ed"):
        forms.extend((lower[:-2], lower[:-1]))
    if lower.endswith("es"):
        forms.extend((lower[:-2], lower[:-1]))
    if lower.endswith("s"):
        forms.append(lower[:-1])
    return next((form for form in forms if form in _ALIASES or form in {"remove", "make"}), None)


def extract_actions(text: str) -> ActionExtraction:  # noqa: PLR0912
    words = list(_WORD.finditer(text))
    evidence: list[ActionEvidence] = []
    unknown = False
    backup_phrases = list(_BACKUP.finditer(text))
    for phrase in backup_phrases:
        evidence.append(ActionEvidence("backup", phrase.group(), phrase.start(), phrase.end()))
    for index, match in enumerate(words):
        if any(phrase.start() <= match.start() < phrase.end() for phrase in backup_phrases):
            continue
        lemma = _lemma(match.group())
        if lemma is None:
            continue
        if (
            lemma == "read"
            and index + 1 < len(words)
            and words[index + 1].group().casefold() in _PERMISSION_TARGETS
        ):
            continue
        if (
            lemma in {"backup", "change"}
            and index > 0
            and any(
                item.group().casefold() in {"a", "an", "the"}
                for item in words[max(0, index - 3) : index]
            )
        ):
            continue
        neighborhood = {word.group().casefold() for word in words[index + 1 : index + 5]}
        if lemma in {"create", "make"} and "backup" in neighborhood:
            value = "backup"
        elif lemma == "make":
            value = "create"
        elif lemma == "remove":
            if neighborhood & _PERMISSION_TARGETS:
                value = "revoke"
            elif neighborhood & _RESOURCE_TARGETS:
                value = "delete"
            else:
                unknown = True
                continue
        else:
            value = _ALIASES[lemma]
        evidence.append(ActionEvidence(value, match.group(), match.start(), match.end()))
    values = {item.value for item in evidence}
    if "run" in values and len(values) > 1:
        evidence = [item for item in evidence if item.value != "run"]
    return ActionExtraction(tuple(evidence), unknown)
