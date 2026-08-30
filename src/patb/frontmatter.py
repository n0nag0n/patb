"""Restricted frontmatter: key: value, key: [a, b]. No nested maps, no PyYAML."""

from __future__ import annotations

from typing import Any


LIST_KEYS = {"aliases", "tags"}


class FrontmatterError(ValueError):
    pass


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def _parse_list(raw: str) -> list[str]:
    inner = raw.strip()
    if not (inner.startswith("[") and inner.endswith("]")):
        raise FrontmatterError(f"not a list: {raw}")
    inner = inner[1:-1].strip()
    if not inner:
        return []
    items: list[str] = []
    buf = []
    in_quote = None
    for ch in inner:
        if in_quote:
            if ch == in_quote:
                in_quote = None
            else:
                buf.append(ch)
            continue
        if ch in "\"'":
            in_quote = ch
            continue
        if ch == ",":
            item = _unquote("".join(buf))
            if item:
                items.append(item)
            buf = []
            continue
        buf.append(ch)
    item = _unquote("".join(buf))
    if item:
        items.append(item)
    return items


def parse_scalar(raw: str) -> Any:
    s = raw.strip()
    if s.startswith("[") and s.endswith("]"):
        return _parse_list(s)
    low = s.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "none", "~"):
        return None
    if s and (s[0] in "\"'"):
        return _unquote(s)
    if s and s[0] in "+-" or s[:1].isdigit():
        try:
            if any(c in s for c in ".eE"):
                return float(s)
            return int(s)
        except ValueError:
            pass
    return s


def parse(text: str) -> tuple[dict[str, Any], str]:
    text = text.replace("\r\n", "\n")
    if not text.startswith("---"):
        return {}, text
    rest = text[3:]
    if rest.startswith("\n"):
        rest = rest[1:]
    end = rest.find("\n---")
    if end < 0:
        raise FrontmatterError("unclosed frontmatter")
    block = rest[:end]
    body = rest[end + 4 :]
    if body.startswith("\n"):
        body = body[1:]
    meta: dict[str, Any] = {}
    for lineno, line in enumerate(block.split("\n"), 1):
        if not line.strip() or line.strip().startswith("#"):
            continue
        if ":" not in line:
            raise FrontmatterError(f"line {lineno}: expected key: value")
        key, val = line.split(":", 1)
        key = key.strip()
        if not key:
            raise FrontmatterError(f"line {lineno}: empty key")
        parsed = parse_scalar(val)
        if key in LIST_KEYS and isinstance(parsed, str):
            parsed = [parsed] if parsed else []
        meta[key] = parsed
    return meta, body


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    s = str(value)
    if any(ch in s for ch in ":[]#,") or s != s.strip() or s.lower() in (
        "true",
        "false",
        "null",
        "yes",
        "no",
    ):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def dump(meta: dict[str, Any], body: str) -> str:
    lines = ["---"]
    for key, value in meta.items():
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, list):
            inner = ", ".join(_fmt(x) for x in value)
            lines.append(f"{key}: [{inner}]")
        else:
            lines.append(f"{key}: {_fmt(value)}")
    lines.append("---")
    lines.append("")
    body = body.rstrip() + "\n"
    return "\n".join(lines) + body
