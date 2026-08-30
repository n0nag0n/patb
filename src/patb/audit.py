"""Refuse secrets in the commitable vault tree."""

from __future__ import annotations

import os
from pathlib import Path

from patb.paths import Paths
from patb.secrets import looks_like_raw_secret


def audit(paths: Paths) -> list[str]:
    issues: list[str] = []
    vault = paths.vault
    if not vault.exists():
        return issues
    for path in vault.rglob("*.md"):
        rel = path.relative_to(vault)
        if "private" in rel.parts:
            continue
        text = path.read_text(encoding="utf-8")
        reason = looks_like_raw_secret(text)
        if reason:
            issues.append(f"{rel}: {reason}")
    try:
        secrets_in_vault = paths.secrets.resolve().is_relative_to(vault.resolve())
    except AttributeError:
        secrets_in_vault = str(paths.secrets.resolve()).startswith(str(vault.resolve()) + os.sep)
    if paths.secrets.exists() and secrets_in_vault:
        issues.append("secrets.env must not live inside the vault")
    return issues
