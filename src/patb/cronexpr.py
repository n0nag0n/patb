"""5-field cron (`m h dom mon dow`) plus @hourly / @daily. No seconds, no month names."""

from __future__ import annotations

from datetime import datetime


class CronError(ValueError):
    pass


MACROS = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
}

BOUNDS = [
    (0, 59),  # minute
    (0, 23),  # hour
    (1, 31),  # day of month
    (1, 12),  # month
    (0, 6),  # day of week (0=Sun)
]


def _parse_field(field: str, lo: int, hi: int) -> set[int]:
    field = field.strip()
    out: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            try:
                step = int(step_s)
            except ValueError as exc:
                raise CronError(f"bad step: {field}") from exc
            if step < 1:
                raise CronError(f"bad step: {field}")
        if part == "*":
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            try:
                start, end = int(a), int(b)
            except ValueError as exc:
                raise CronError(f"bad range: {field}") from exc
        else:
            try:
                start = end = int(part)
            except ValueError as exc:
                raise CronError(f"bad field: {field}") from exc
        if start < lo or end > hi or start > end:
            raise CronError(f"out of range: {field}")
        out.update(range(start, end + 1, step))
    if not out:
        raise CronError(f"empty field: {field}")
    return out


def parse(expr: str) -> list[set[int]]:
    expr = expr.strip()
    if expr in MACROS:
        expr = MACROS[expr]
    parts = expr.split()
    if len(parts) != 5:
        raise CronError(f"expected 5 fields or a @macro, got {expr!r}")
    return [_parse_field(parts[i], *BOUNDS[i]) for i in range(5)]


def matches(expr: str, when: datetime) -> bool:
    fields = parse(expr)
    dow = when.weekday() + 1  # Mon=1 .. Sun=7
    if dow == 7:
        dow = 0
    return (
        when.minute in fields[0]
        and when.hour in fields[1]
        and when.day in fields[2]
        and when.month in fields[3]
        and dow in fields[4]
    )
