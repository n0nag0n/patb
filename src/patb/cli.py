"""patb CLI. Agents query this; they do not guess keys."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from patb import __version__
from patb.audit import audit
from patb.core import check as core_check
from patb.core import core_text, stamp
from patb.paths import Paths
from patb.secrets import (
    SecretError,
    expand,
    has_secret,
    load as load_secrets,
    names_missing_placeholder,
    set_secret,
)
from patb.store import KINDS, Store
from patb.tick import due_jobs, install_crontab, tick as run_tick, uninstall_crontab


USAGE = """patb — look up one standing instruction (not the whole catalog).

  patb get KEY                 exact key or alias; expands ${NAME}
  patb search "tire size"      2-4 keywords, not the whole sentence
  patb query --domain email --tag silent-delete
  patb set KEY --kind policy --body "..."
  patb propose / patb accept   candidates → locked
  patb secret set NAME         value on stdin; never in markdown
  patb reindex                 vault markdown → sqlite
  patb dump / patb import      JSONL belt (no secret values)
  patb core                    paste this into every agent profile

Grok Bot clock: a Grok routine per job whose prompt is only
  patb get job.<name>
Do not schedule 'patb due' every minute.

Linux clock (has crontab): patb tick / patb cron install
"""


def _paths(ns: argparse.Namespace) -> Paths:
    home = Path(ns.home) if getattr(ns, "home", None) else None
    return Paths(home)


def _agent(ns: argparse.Namespace) -> str | None:
    return getattr(ns, "agent", None) or os.environ.get("PATB_AGENT") or None


def _json(ns: argparse.Namespace) -> bool:
    return bool(getattr(ns, "json", False))


def _store(ns: argparse.Namespace, reindex_if_stale: bool = True) -> Store:
    store = Store(_paths(ns))
    if reindex_if_stale:
        store.maybe_reindex()
    return store


def _print_rec(
    rec: dict[str, Any],
    secrets: dict[str, str],
    as_json: bool,
    full: bool = True,
    *,
    expand_secrets: bool = False,
) -> None:
    body_raw = rec.get("body") or ""
    body = expand(body_raw, secrets) if expand_secrets else body_raw
    if as_json:
        payload = {
            "key": rec["key"],
            "kind": rec.get("kind"),
            "summary": rec.get("summary"),
            "approval": rec.get("approval"),
            "tier": rec.get("tier"),
            "domain": rec.get("domain"),
            "path": rec.get("path"),
            "aliases": rec.get("aliases") or [],
            "tags": rec.get("tags") or [],
        }
        if full:
            payload["body"] = body
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return
    if full:
        sys.stdout.write(f"# {rec['key']}\n{body}")
        if not body.endswith("\n"):
            sys.stdout.write("\n")
    else:
        summary = rec.get("summary") or ""
        sys.stdout.write(f"{rec['key']}\t{rec.get('kind')}\t{summary}\n")


def _warn_missing_placeholders(body: str, secrets: dict[str, str]) -> None:
    for name in names_missing_placeholder(body, secrets):
        sys.stderr.write(
            f"warn: this record names {name} without ${{{name}}}, so get cannot print it; "
            "put the placeholder in the record; do not open secrets.env\n"
        )


def cmd_root(_ns: argparse.Namespace) -> int:
    sys.stdout.write(USAGE)
    return 0


def cmd_core(ns: argparse.Namespace) -> int:
    paths = _paths(ns)
    if ns.check:
        ok, msg = core_check(paths)
        sys.stdout.write(msg + "\n")
        return 0 if ok else 1
    text = core_text()
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    stamp(paths)
    return 0


def cmd_get(ns: argparse.Namespace) -> int:
    store = _store(ns)
    rec = store.get(ns.key, agent=_agent(ns), bump=True)
    if not rec:
        store.log_miss(ns.key)
        sys.stderr.write(f"not found: {ns.key}\n")
        return 1
    secrets = load_secrets(store.paths.secrets)
    _warn_missing_placeholders(rec.get("body") or "", secrets)
    _print_rec(rec, secrets, _json(ns), full=True, expand_secrets=True)
    return 0


def cmd_search(ns: argparse.Namespace) -> int:
    store = _store(ns)
    rows = store.search(ns.q, agent=_agent(ns), archive=ns.archive, limit=ns.limit)
    if _json(ns):
        json.dump(
            [
                {
                    "key": r["key"],
                    "kind": r.get("kind"),
                    "summary": r.get("summary"),
                    "score": r.get("_score"),
                    "body": (r.get("body") or "") if ns.full else None,
                }
                for r in rows
            ],
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0
    if not rows:
        sys.stderr.write("no hits (logged as miss/candidate)\n")
        return 1
    for r in rows:
        _print_rec(r, {}, False, full=ns.full)
    return 0


def cmd_query(ns: argparse.Namespace) -> int:
    store = _store(ns)
    rows = store.query(
        domain=ns.domain,
        tag=ns.tag,
        kind=ns.kind,
        circle=ns.circle,
        agent=_agent(ns),
        src=ns.src,
        archive=ns.archive,
        limit=ns.limit,
    )
    if _json(ns):
        json.dump(
            [
                {
                    "key": r["key"],
                    "kind": r.get("kind"),
                    "summary": r.get("summary"),
                    "path": r.get("path"),
                    "body": (r.get("body") or "") if ns.full else None,
                }
                for r in rows
            ],
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0
    for r in rows:
        _print_rec(r, {}, False, full=ns.full)
    return 0 if rows else 1


def cmd_reindex(ns: argparse.Namespace) -> int:
    store = Store(_paths(ns))
    n = store.reindex()
    sys.stdout.write(f"indexed {n} files\n")
    return 0


def cmd_set(ns: argparse.Namespace) -> int:
    store = _store(ns)
    body = ns.body
    if ns.body_file:
        body = Path(ns.body_file).read_text(encoding="utf-8") if ns.body_file != "-" else sys.stdin.read()
    if body is None:
        sys.stderr.write("need --body or --body-file\n")
        return 2
    rec = {
        "key": ns.key,
        "kind": ns.kind,
        "domain": ns.domain,
        "summary": ns.summary,
        "body": body,
        "approval": ns.approval,
        "tier": ns.tier,
        "importance": ns.importance,
        "sensitivity": ns.sensitivity,
        "agent_key": ns.agent_key or _agent(ns),
        "schedule": ns.schedule,
        "timezone": ns.timezone,
        "notify": ns.notify,
        "exec_cmd": ns.exec_cmd,
        "webhook_url_secret": ns.webhook_url_secret,
        "webhook_key_secret": ns.webhook_key_secret,
        "circle": ns.circle,
    }
    try:
        path = store.set_record(rec, ns.alias or [], ns.tag or [])
    except ValueError as exc:
        sys.stderr.write(str(exc) + "\n")
        return 2
    sys.stdout.write(f"wrote {path}\n")
    return 0


def cmd_propose(ns: argparse.Namespace) -> int:
    ns.kind = ns.kind or "candidate"
    ns.tier = "candidate"
    return cmd_set(ns)


def cmd_accept(ns: argparse.Namespace) -> int:
    store = _store(ns)
    try:
        path = store.accept(ns.key)
    except KeyError:
        sys.stderr.write(f"not found: {ns.key}\n")
        return 1
    sys.stdout.write(f"accepted {ns.key} -> {path}\n")
    return 0


def cmd_secret(ns: argparse.Namespace) -> int:
    paths = _paths(ns)
    paths.ensure_home()
    if ns.secret_cmd == "has":
        sys.stdout.write("yes\n" if has_secret(paths, ns.name) else "no\n")
        return 0 if has_secret(paths, ns.name) else 1
    if ns.secret_cmd == "set":
        value = sys.stdin.read()
        if value.endswith("\n") and value.count("\n") == 1:
            value = value[:-1]
        try:
            set_secret(paths, ns.name, value)
        except SecretError as exc:
            sys.stderr.write(str(exc) + "\n")
            return 2
        sys.stdout.write(f"set {ns.name}\n")
        return 0
    sys.stderr.write("usage: patb secret set NAME   (value on stdin)\n")
    return 2


def cmd_dump(ns: argparse.Namespace) -> int:
    store = _store(ns)
    rows = store.dump_records(public=ns.public)
    dest = Path(ns.output) if ns.output else None
    text = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
    if dest:
        dest.write_text(text, encoding="utf-8")
        sys.stdout.write(f"wrote {len(rows)} records to {dest}\n")
    else:
        sys.stdout.write(text)
    return 0


def cmd_import(ns: argparse.Namespace) -> int:
    store = _store(ns, reindex_if_stale=False)
    src = Path(ns.file)
    items = []
    for line in src.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            items.append(json.loads(line))
    n = store.import_records(items)
    sys.stdout.write(f"imported {n}\n")
    return 0


def cmd_due(ns: argparse.Namespace) -> int:
    store = _store(ns)
    jobs = due_jobs(store)
    if _json(ns):
        json.dump([{"key": j["key"], "schedule": j.get("schedule"), "agent": j.get("agent_key")} for j in jobs], sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        if not jobs:
            sys.stdout.write("nothing due\n")
        for j in jobs:
            sys.stdout.write(f"{j['key']}\t{j.get('schedule')}\t{j.get('agent_key') or ''}\n")
    return 0


def cmd_tick(ns: argparse.Namespace) -> int:
    paths = _paths(ns)
    store = Store(paths)
    store.maybe_reindex()
    result = run_tick(paths, store)
    if _json(ns):
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        if result.get("skipped"):
            sys.stdout.write(f"skipped: {result['skipped']}\n")
        elif not result["fired"]:
            sys.stdout.write("nothing due\n")
        for item in result["fired"]:
            status = "ok" if item.get("ok") else "fail"
            sys.stdout.write(f"{status}\t{item.get('key')}\t{item.get('error') or item.get('status') or ''}\n")
    return 0


def cmd_cron(ns: argparse.Namespace) -> int:
    bin_path = ns.bin or sys.argv[0]
    bin_path = str(Path(bin_path).resolve())
    try:
        if ns.cron_cmd == "install":
            sys.stdout.write(install_crontab(bin_path) + "\n")
        else:
            sys.stdout.write(uninstall_crontab(bin_path) + "\n")
    except RuntimeError as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1
    return 0


def cmd_miss(ns: argparse.Namespace) -> int:
    store = _store(ns)
    rows = store.misses()
    if _json(ns):
        json.dump(rows, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return 0
    for r in rows:
        sys.stdout.write(f"{r['at']}\t{r['guessed']}\n")
    return 0


def cmd_audit(ns: argparse.Namespace) -> int:
    issues = audit(_paths(ns))
    if not issues:
        sys.stdout.write("ok\n")
        return 0
    for i in issues:
        sys.stderr.write(i + "\n")
    return 1


def cmd_consolidate(ns: argparse.Namespace) -> int:
    store = _store(ns)
    result = store.consolidate()
    if _json(ns):
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(f"demoted {len(result['demoted'])} working → episodic\n")
        for k in result["hot_candidates"]:
            sys.stdout.write(f"hot candidate (accept?): {k}\n")
    return 0


def cmd_relate(ns: argparse.Namespace) -> int:
    store = _store(ns)
    store.add_relation(ns.src, ns.dest, ns.circle, ns.note or "")
    sys.stdout.write(f"{ns.src} -> {ns.dest} ({ns.circle})\n")
    return 0


def _add_global(p: argparse.ArgumentParser) -> None:
    p.add_argument("--home", default=argparse.SUPPRESS, help="PATB_HOME override")
    p.add_argument("--agent", default=argparse.SUPPRESS, help="PATB_AGENT override")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="patb", add_help=True, description="Query one decision at a time.")
    p.add_argument("--version", action="version", version=f"patb {__version__}")
    _add_global(p)
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("core", help="print versioned CORE for agent profiles")
    _add_global(s)
    s.add_argument("--check", action="store_true")
    s.set_defaults(func=cmd_core)

    s = sub.add_parser("get", help="exact key or alias")
    _add_global(s)
    s.add_argument("key")
    s.set_defaults(func=cmd_get)

    s = sub.add_parser("search", help="alias then keywords")
    _add_global(s)
    s.add_argument("q")
    s.add_argument("--archive", action="store_true")
    s.add_argument("--full", action="store_true")
    s.add_argument("--limit", type=int, default=8)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("query", help="relational filter")
    _add_global(s)
    s.add_argument("--domain")
    s.add_argument("--tag")
    s.add_argument("--kind", choices=KINDS)
    s.add_argument("--circle", choices=["family", "friend", "work"])
    s.add_argument("--from", dest="src")
    s.add_argument("--archive", action="store_true")
    s.add_argument("--full", action="store_true")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=cmd_query)

    s = sub.add_parser("reindex", help="rebuild sqlite from vault markdown")
    _add_global(s)
    s.set_defaults(func=cmd_reindex)

    def set_flags(sp: argparse.ArgumentParser) -> None:
        _add_global(sp)
        sp.add_argument("key")
        sp.add_argument("--kind", default="policy", choices=KINDS)
        sp.add_argument("--domain")
        sp.add_argument("--summary")
        sp.add_argument("--body")
        sp.add_argument("--body-file")
        sp.add_argument("--alias", action="append")
        sp.add_argument("--tag", action="append")
        sp.add_argument("--approval", default="none")
        sp.add_argument("--tier", default="locked")
        sp.add_argument("--importance", type=float, default=1.0)
        sp.add_argument("--sensitivity", default="public", choices=["public", "private"])
        sp.add_argument("--agent-key")
        sp.add_argument("--schedule")
        sp.add_argument("--timezone")
        sp.add_argument("--notify", choices=["webhook", "exec"])
        sp.add_argument("--exec-cmd")
        sp.add_argument("--webhook-url-secret")
        sp.add_argument("--webhook-key-secret")
        sp.add_argument("--circle", choices=["family", "friend", "work"])

    s = sub.add_parser("set", help="write sqlite + markdown")
    set_flags(s)
    s.set_defaults(func=cmd_set)

    s = sub.add_parser("propose", help="write a candidate")
    set_flags(s)
    s.set_defaults(func=cmd_propose)

    s = sub.add_parser("accept", help="promote candidate to locked")
    _add_global(s)
    s.add_argument("key")
    s.set_defaults(func=cmd_accept)

    s = sub.add_parser("secret", help="set/has secrets (stdin in; no dump)")
    _add_global(s)
    ss = s.add_subparsers(dest="secret_cmd")
    pset = ss.add_parser("set")
    _add_global(pset)
    pset.add_argument("name")
    pset.set_defaults(func=cmd_secret)
    phas = ss.add_parser("has")
    _add_global(phas)
    phas.add_argument("name")
    phas.set_defaults(func=cmd_secret)

    s = sub.add_parser("dump", help="JSONL snapshot (placeholders, not secret values)")
    _add_global(s)
    s.add_argument("-o", "--output")
    s.add_argument("--public", action="store_true")
    s.set_defaults(func=cmd_dump)

    s = sub.add_parser("import", help="import JSONL into vault + sqlite")
    _add_global(s)
    s.add_argument("file")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("due", help="jobs that would fire now")
    _add_global(s)
    s.set_defaults(func=cmd_due)

    s = sub.add_parser("tick", help="fire due jobs (for crontab)")
    _add_global(s)
    s.set_defaults(func=cmd_tick)

    s = sub.add_parser("cron", help="install/uninstall user crontab")
    _add_global(s)
    cs = s.add_subparsers(dest="cron_cmd")
    ins = cs.add_parser("install")
    _add_global(ins)
    ins.add_argument("--bin")
    ins.set_defaults(func=cmd_cron)
    uns = cs.add_parser("uninstall")
    _add_global(uns)
    uns.add_argument("--bin")
    uns.set_defaults(func=cmd_cron)

    s = sub.add_parser("miss", help="unresolved lookup misses")
    _add_global(s)
    s.set_defaults(func=cmd_miss)

    s = sub.add_parser("audit", help="fail if secrets leaked into git vault")
    _add_global(s)
    s.set_defaults(func=cmd_audit)

    s = sub.add_parser("consolidate", help="daily memory moves; never edits CORE")
    _add_global(s)
    s.set_defaults(func=cmd_consolidate)

    s = sub.add_parser("relate", help="agent/person relation")
    _add_global(s)
    s.add_argument("src")
    s.add_argument("dest")
    s.add_argument("--circle", default="work", choices=["family", "friend", "work"])
    s.add_argument("--note")
    s.set_defaults(func=cmd_relate)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not argv:
        sys.stdout.write(USAGE)
        return 0
    ns = parser.parse_args(argv)
    func = getattr(ns, "func", None)
    if not func:
        sys.stdout.write(USAGE)
        return 0
    return func(ns)
