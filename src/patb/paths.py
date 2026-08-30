"""Resolve PATB_HOME / vault / sqlite / secrets."""

from __future__ import annotations

import os
from pathlib import Path

from patb.guard import chmod_private

VAULT_GITIGNORE = "private/\n*.sqlite\n*.sqlite-*\nsecrets.env\n"


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
        chmod_private(self.home, 0o700)
        self.vault.mkdir(parents=True, exist_ok=True)
        priv = self.vault / "private"
        priv.mkdir(exist_ok=True)
        chmod_private(priv, 0o700)
        (self.vault / "inbox").mkdir(exist_ok=True)
        gi = self.vault / ".gitignore"
        if not gi.exists():
            gi.write_text(VAULT_GITIGNORE, encoding="utf-8")
        elif "*.sqlite-*" not in gi.read_text(encoding="utf-8"):
            text = gi.read_text(encoding="utf-8").rstrip() + "\n*.sqlite-*\n"
            gi.write_text(text, encoding="utf-8")
