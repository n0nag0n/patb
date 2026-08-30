"""Resolve PATB_HOME / vault / sqlite / secrets."""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_home() -> Path:
    override = os.environ.get("PATB_HOME")
    if override:
        return Path(override).expanduser().resolve()
    workspace = Path("/workspace")
    try:
        if workspace.is_dir() and os.access(workspace, os.W_OK):
            return (workspace / "patb").resolve()
    except OSError:
        pass
    return (Path.home() / ".patb").resolve()


class Paths:
    def __init__(self, home: Path | None = None) -> None:
        self.home = (home or default_home()).resolve()
        vault_override = os.environ.get("PATB_VAULT")
        self.vault = (
            Path(vault_override).expanduser().resolve()
            if vault_override
            else self.home / "vault"
        )
        self.sqlite = self.home / "index.sqlite"
        self.secrets = self.home / "secrets.env"
        self.tick_lock = self.home / "tick.lock"
        self.core_stamp = self.home / "core.version"
        self.relations = self.vault / "relations.jsonl"

    def ensure_home(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.vault.mkdir(parents=True, exist_ok=True)
        (self.vault / "private").mkdir(exist_ok=True)
        (self.vault / "inbox").mkdir(exist_ok=True)
        gi = self.vault / ".gitignore"
        if not gi.exists():
            gi.write_text(
                "private/\n*.sqlite\nsecrets.env\n",
                encoding="utf-8",
            )
