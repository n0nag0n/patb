"""Versioned CORE text agents paste into every profile."""

from __future__ import annotations

import hashlib
from pathlib import Path

from patb import CORE_VERSION, __version__
from patb.paths import Paths, repo_root

CORE_TEXT = f"""patb CORE {CORE_VERSION}
You have the `patb` CLI. Before you act, query it.
You may run patb as many times as this task needs. Fetch only the current step.
Do not guess keys. Do not dump the catalog. Do not read secrets.env or index.sqlite.
If patb is missing: export PATH="$HOME/.local/bin:$PATH"

Look up with `patb search` and 2-4 keywords, not the whole utterance.
Good: patb search "tire size cadenza"  Bad: the full sentence.
If it misses, try fewer words. Do not invent a key.

When a record or the situation needs a human choice, present a numbered list.
Numbers must be unique in that message. Wait.

Obey the record's approval field.
If a webhook payload has a "key", run `patb get <key>` and follow only that body.
To store an address, webhook, API key, or password: `patb secret set NAME` (value on stdin),
then put ${{NAME}} in the record. Never write the raw value into markdown or chat.
"""


def core_text() -> str:
    path = repo_root() / "CORE.md"
    if path.exists():
        return path.read_text(encoding="utf-8").strip() + "\n"
    return CORE_TEXT if CORE_TEXT.endswith("\n") else CORE_TEXT + "\n"


def core_hash(text: str | None = None) -> str:
    return hashlib.sha256((text or core_text()).encode("utf-8")).hexdigest()[:16]


def stamp(paths: Paths) -> None:
    paths.ensure_home()
    paths.core_stamp.write_text(f"{__version__} {core_hash()}\n", encoding="utf-8")


def check(paths: Paths) -> tuple[bool, str]:
    expected = f"{__version__} {core_hash()}"
    if not paths.core_stamp.exists():
        return False, f"no stamp (run `patb core` and paste into agents). current {expected}"
    got = paths.core_stamp.read_text(encoding="utf-8").strip()
    if got == expected:
        return True, f"ok {expected}"
    return False, f"stale {got!r}; current {expected}. run `patb core` and update agent profiles"
