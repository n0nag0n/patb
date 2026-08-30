"""secrets.env: KEY=value, mode 0600. Expand ${NAME} on get. No dump of values."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Iterable
from pathlib import Path

from patb.paths import Paths

NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
EXPAND_RE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
# Tight mismatch: prose "patb secret NAME" instead of ${NAME}. Does not match "set"/"has".
PROSE_SECRET_RE = re.compile(r"\bpatb secret ([A-Z][A-Z0-9_]*)\b")

# Raw values we refuse to store in markdown bodies.
SECRETISH = [
    re.compile(r"https://api2\.cursor\.sh/automations/webhook/\S+", re.I),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-/=+]{12,}", re.I),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


class SecretError(ValueError):
    pass


def load(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if NAME_RE.match(k):
            out[k] = v
    return out


def save(path: Path, data: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# patb secrets — do not commit\n"]
    for k in sorted(data):
        v = data[k].replace("\\", "\\\\").replace("\n", "\\n")
        lines.append(f"{k}={v}\n")
    path.write_text("".join(lines), encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def set_secret(paths: Paths, name: str, value: str) -> None:
    name = name.strip()
    if not NAME_RE.match(name):
        raise SecretError("secret name must be A-Z, digits, underscore (e.g. HOME_ADDRESS)")
    if not value:
        raise SecretError("empty secret")
    data = load(paths.secrets)
    data[name] = value
    save(paths.secrets, data)


def has_secret(paths: Paths, name: str) -> bool:
    return name in load(paths.secrets)


def expand(text: str, data: dict[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in data:
            return m.group(0)
        return data[key]

    return EXPAND_RE.sub(repl, text)


def names_missing_placeholder(body: str, known_names: Iterable[str] = ()) -> list[str]:
    """Names the body refers to without a ${NAME} placeholder.

    Warns only for names `patb secret` has, or the tight prose mismatch
    ``patb secret NAME``. Random ALL_CAPS words do not count.
    """
    placeholders = set(EXPAND_RE.findall(body))
    mentioned: set[str] = set()
    for match in PROSE_SECRET_RE.finditer(body):
        mentioned.add(match.group(1))
    stripped = EXPAND_RE.sub("", body)
    for name in known_names:
        if not NAME_RE.match(name):
            continue
        if re.search(r"\b" + re.escape(name) + r"\b", stripped):
            mentioned.add(name)
    return sorted(name for name in mentioned if name not in placeholders)


def looks_like_raw_secret(text: str) -> str | None:
    """Return a reason if markdown must not contain this as a raw value."""
    if EXPAND_RE.search(text) and not any(p.search(EXPAND_RE.sub("", text)) for p in SECRETISH):
        # has placeholders; still flag leftover raw webhook urls
        pass
    for pat in SECRETISH:
        if pat.search(text):
            return "looks like a webhook, token, or private key — use `patb secret set NAME` and ${NAME}"
    return None
