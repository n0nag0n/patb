"""Refuse secrets in the commitable vault tree. Check perms and exec allowlist."""

from __future__ import annotations

import os

from patb import frontmatter
from patb.guard import GuardError, confine_to_dir, exec_argv, mode_ok
from patb.paths import Paths
from patb.secrets import looks_like_raw_secret


def audit(paths: Paths) -> list[str]:
    issues: list[str] = []
    vault = paths.vault
    if vault.exists():
        root = vault.resolve()
        for path in vault.rglob("*.md"):
            try:
                confine_to_dir(root, path)
            except GuardError as exc:
                issues.append(str(exc))
                continue
            rel = path.relative_to(vault)
            if "private" in rel.parts:
                continue
            text = path.read_text(encoding="utf-8")
            reason = looks_like_raw_secret(text)
            if reason:
                issues.append(f"{rel}: {reason}")
            try:
                meta, _ = frontmatter.parse(text)
            except frontmatter.FrontmatterError:
                continue
            if str(meta.get("notify") or "") == "exec":
                try:
                    exec_argv(str(meta.get("exec") or ""))
                except GuardError as exc:
                    issues.append(f"{rel}: {exc}")
    try:
        secrets_in_vault = paths.secrets.resolve().is_relative_to(vault.resolve())
    except (AttributeError, FileNotFoundError):
        secrets_in_vault = str(paths.secrets.resolve()).startswith(str(vault.resolve()) + os.sep)
    if paths.secrets.exists() and secrets_in_vault:
        issues.append("secrets.env must not live inside the vault")
    if paths.secrets.exists() and not mode_ok(paths.secrets, 0o600):
        issues.append("secrets.env must be mode 0600")
    if paths.sqlite.exists() and not mode_ok(paths.sqlite, 0o600):
        issues.append("index.sqlite must be mode 0600")
    if paths.home.exists():
        try:
            if paths.home.stat().st_mode & 0o077:
                issues.append("PATB_HOME must not be group/world-accessible")
        except OSError:
            pass
    return issues
