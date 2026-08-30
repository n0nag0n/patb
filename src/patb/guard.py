"""Local-CLI guards: keys stay in the vault, exec is allowlisted, webhooks are public https."""

from __future__ import annotations

import ipaddress
import os
import re
import shlex
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
SAFE_EXEC_SUBCOMMANDS = frozenset({"consolidate", "reindex", "audit", "due", "core"})
BLOCKED_HOSTS = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"})


class GuardError(ValueError):
    pass


def valid_key(key: str, *, label: str = "key") -> str:
    key = (key or "").strip()
    if not KEY_RE.match(key) or "" in key.split("."):
        raise GuardError(
            f"{label} must be letters, digits, dot, underscore, hyphen "
            "(e.g. email.usps, protocol.global)"
        )
    return key


def confine_to_dir(root: Path, path: Path) -> Path:
    """Resolve path and require it stay under root. Raises GuardError otherwise."""
    root_r = root.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(root_r)
    except ValueError as exc:
        raise GuardError(f"path escapes {root_r}") from exc
    return resolved


def iter_vault_markdown(vault: Path):
    """Yield *.md files whose resolved path stays under vault. Skip CORE.md."""
    if not vault.exists():
        return
    root = vault.resolve()
    for path in sorted(vault.rglob("*.md")):
        if path.name.lower() == "core.md":
            continue
        try:
            confine_to_dir(root, path)
        except GuardError as exc:
            raise GuardError(f"{path}: {exc}") from exc
        yield path


def exec_argv(cmd: str) -> list[str]:
    """Allow only `patb <subcommand>` with no extra argv. Return process argv."""
    cmd = (cmd or "").strip()
    if not cmd:
        raise GuardError("no exec")
    try:
        parts = shlex.split(cmd)
    except ValueError as exc:
        raise GuardError("invalid exec") from exc
    if len(parts) != 2 or parts[0] != "patb":
        raise GuardError("exec must be `patb <subcommand>` with no extra args")
    if parts[1] not in SAFE_EXEC_SUBCOMMANDS:
        raise GuardError(
            "exec subcommand not allowed (consolidate, reindex, audit, due, core)"
        )
    return [sys.executable, "-m", "patb", parts[1]]


def _ip_blocked(ip: ipaddress._BaseAddress) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def check_webhook_url(url: str, *, resolve_host: bool = False) -> str | None:
    """Return an error string if url is not a public https target."""
    if not url or not isinstance(url, str):
        return "empty webhook url"
    if any(ch in url for ch in " \t\r\n"):
        return "invalid webhook url"
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return "webhook url must be https"
    host = parsed.hostname
    if not host:
        return "webhook url missing host"
    if parsed.username or parsed.password:
        return "webhook url must not include userinfo"
    if host.lower().rstrip(".") in BLOCKED_HOSTS:
        return "webhook host is not a public address"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and _ip_blocked(ip):
        return "webhook host is not a public address"
    if not resolve_host:
        return None
    port = parsed.port or 443
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return "webhook host did not resolve"
    for info in infos:
        addr = info[4][0]
        try:
            resolved = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _ip_blocked(resolved):
            return "webhook host is not a public address"
    return None


def chmod_private(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def mode_ok(path: Path, expected: int) -> bool:
    if not path.exists():
        return True
    try:
        return stat_mode(path) & 0o777 == expected
    except OSError:
        return False


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777
