"""SQLite live index. Markdown vault is the git copy of the same records."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from patb import frontmatter
from patb.paths import Paths
from patb.secrets import looks_like_raw_secret

KINDS = (
    "protocol",
    "policy",
    "job",
    "agent",
    "identity",
    "working",
    "episodic",
    "candidate",
)
TIERS = ("locked", "working", "episodic", "candidate")
TIER_WEIGHT = {
    "locked": 4.0,
    "working": 3.0,
    "episodic": 1.0,
    "candidate": 0.5,
}
CIRCLE_WEIGHT = {"family": 1.3, "friend": 1.1, "work": 1.0}
SHARED_KINDS = {"protocol", "policy", "job", "agent", "identity"}
EPISODIC_HIDE_DAYS = 30.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    domain TEXT,
    summary TEXT,
    body TEXT NOT NULL,
    path TEXT,
    hash TEXT,
    schedule TEXT,
    timezone TEXT,
    approval TEXT DEFAULT 'none',
    tier TEXT NOT NULL DEFAULT 'locked',
    importance REAL NOT NULL DEFAULT 1.0,
    sensitivity TEXT NOT NULL DEFAULT 'public',
    agent_key TEXT,
    notify TEXT,
    exec_cmd TEXT,
    webhook_url_secret TEXT,
    webhook_key_secret TEXT,
    circle TEXT,
    retrievals INTEGER NOT NULL DEFAULT 0,
    last_retrieved_at TEXT,
    last_run_at TEXT,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS aliases (
    alias TEXT PRIMARY KEY,
    key TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tags (
    key TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (key, tag)
);
CREATE TABLE IF NOT EXISTS relations (
    from_key TEXT NOT NULL,
    to_key TEXT NOT NULL,
    circle TEXT NOT NULL,
    note TEXT,
    PRIMARY KEY (from_key, to_key)
);
CREATE TABLE IF NOT EXISTS misses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guessed TEXT NOT NULL,
    at TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_records_kind ON records(kind);
CREATE INDEX IF NOT EXISTS idx_records_domain ON records(domain);
CREATE INDEX IF NOT EXISTS idx_records_agent ON records(agent_key);
CREATE INDEX IF NOT EXISTS idx_records_tier ON records(tier);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, str) and value:
        return [value]
    return []


def record_path(vault: Path, rec: dict[str, Any]) -> Path:
    key = rec["key"]
    kind = rec.get("kind") or "policy"
    sensitivity = rec.get("sensitivity") or "public"
    parts = key.split(".")
    if kind == "protocol":
        rel = Path("protocols") / ".".join(parts[1:] or parts)
    elif kind == "policy":
        if len(parts) >= 2:
            rel = Path("policies") / parts[0] / "/".join(parts[1:])
        else:
            rel = Path("policies") / key
    elif kind == "job":
        rel = Path("jobs") / ".".join(parts[1:] or parts)
    elif kind == "agent":
        rel = Path("agents") / ".".join(parts[1:] or parts)
    elif kind == "identity":
        rel = Path("identity") / ".".join(parts[1:] or parts)
    elif kind == "working":
        rel = Path("working") / (rec.get("agent_key") or "shared") / key
    elif kind == "episodic":
        rel = Path("episodic") / (rec.get("agent_key") or "shared") / key
    else:
        rel = Path("inbox") / key
    rel = Path(str(rel) + ".md")
    if sensitivity == "private":
        return vault / "private" / rel
    return vault / rel


def record_to_meta(rec: dict[str, Any], aliases: list[str], tags: list[str]) -> dict[str, Any]:
    meta = {
        "key": rec["key"],
        "kind": rec.get("kind"),
        "domain": rec.get("domain"),
        "aliases": aliases,
        "tags": tags,
        "summary": rec.get("summary"),
        "approval": rec.get("approval") or "none",
        "tier": rec.get("tier") or "locked",
        "importance": rec.get("importance", 1.0),
        "sensitivity": rec.get("sensitivity") or "public",
        "agent": rec.get("agent_key"),
        "schedule": rec.get("schedule"),
        "timezone": rec.get("timezone"),
        "notify": rec.get("notify"),
        "exec": rec.get("exec_cmd"),
        "webhook_url_secret": rec.get("webhook_url_secret"),
        "webhook_key_secret": rec.get("webhook_key_secret"),
        "circle": rec.get("circle"),
    }
    return {k: v for k, v in meta.items() if v not in (None, "", [])}


def write_markdown(vault: Path, rec: dict[str, Any], aliases: list[str], tags: list[str]) -> Path:
    path = record_path(vault, rec)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = frontmatter.dump(record_to_meta(rec, aliases, tags), rec.get("body") or "")
    path.write_text(text, encoding="utf-8")
    return path


class Store:
    def __init__(self, paths: Paths) -> None:
        self.paths = paths
        paths.ensure_home()
        self.conn = sqlite3.connect(str(paths.sqlite))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        try:
            self.conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5("
                "key, aliases, summary, tags, body, tokenize='unicode61')"
            )
            self._fts = True
        except sqlite3.OperationalError:
            self._fts = False
        self.conn.commit()

    def maybe_reindex(self) -> bool:
        db = self.paths.sqlite
        if not db.exists() or db.stat().st_size == 0:
            self.reindex()
            return True
        vault = self.paths.vault
        if not vault.exists():
            return False
        newest = 0.0
        for p in vault.rglob("*.md"):
            try:
                newest = max(newest, p.stat().st_mtime)
            except OSError:
                continue
        if self.paths.relations.exists():
            newest = max(newest, self.paths.relations.stat().st_mtime)
        if newest and newest > db.stat().st_mtime + 0.5:
            self.reindex()
            return True
        return False

    def reindex(self) -> int:
        runtime = self._snapshot_runtime()
        self.conn.execute("DELETE FROM records")
        self.conn.execute("DELETE FROM aliases")
        self.conn.execute("DELETE FROM tags")
        self.conn.execute("DELETE FROM relations")
        if self._fts:
            self.conn.execute("DELETE FROM records_fts")
        count = 0
        vault = self.paths.vault
        if vault.exists():
            for path in sorted(vault.rglob("*.md")):
                if path.name.lower() == "core.md":
                    continue
                try:
                    self._index_file(path, runtime)
                    count += 1
                except (frontmatter.FrontmatterError, ValueError) as exc:
                    raise ValueError(f"{path}: {exc}") from exc
        self._load_relations_file()
        self.conn.commit()
        return count

    def _snapshot_runtime(self) -> dict[str, dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT key, retrievals, last_retrieved_at, last_run_at FROM records"
        ).fetchall()
        return {r["key"]: dict(r) for r in rows}

    def _index_file(self, path: Path, runtime: dict[str, dict[str, Any]]) -> None:
        text = path.read_text(encoding="utf-8")
        meta, body = frontmatter.parse(text)
        key = str(meta.get("key") or "").strip()
        if not key:
            raise ValueError("missing key")
        kind = str(meta.get("kind") or "policy")
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind}")
        rec = {
            "key": key,
            "kind": kind,
            "domain": meta.get("domain"),
            "summary": meta.get("summary"),
            "body": body,
            "path": str(path.relative_to(self.paths.vault)),
            "hash": _hash(text),
            "schedule": meta.get("schedule"),
            "timezone": meta.get("timezone"),
            "approval": meta.get("approval") or "none",
            "tier": meta.get("tier") or ("candidate" if kind == "candidate" else "locked"),
            "importance": float(meta.get("importance") or 1.0),
            "sensitivity": meta.get("sensitivity") or "public",
            "agent_key": meta.get("agent") or meta.get("agent_key"),
            "notify": meta.get("notify"),
            "exec_cmd": meta.get("exec"),
            "webhook_url_secret": meta.get("webhook_url_secret"),
            "webhook_key_secret": meta.get("webhook_key_secret"),
            "circle": meta.get("circle"),
            "retrievals": 0,
            "last_retrieved_at": None,
            "last_run_at": None,
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
        }
        if rec["tier"] not in TIERS:
            rec["tier"] = "locked"
        if rec["sensitivity"] == "private":
            rel = Path(rec["path"])
            if "private" not in rel.parts:
                raise ValueError("sensitivity: private records must live under vault/private/")
        rt = runtime.get(key)
        if rt:
            rec["retrievals"] = rt["retrievals"] or 0
            rec["last_retrieved_at"] = rt["last_retrieved_at"]
            rec["last_run_at"] = rt["last_run_at"]
        self._upsert_record(rec, _as_list(meta.get("aliases")), _as_list(meta.get("tags")))

    def _upsert_record(self, rec: dict[str, Any], aliases: list[str], tags: list[str]) -> None:
        cols = [
            "key",
            "kind",
            "domain",
            "summary",
            "body",
            "path",
            "hash",
            "schedule",
            "timezone",
            "approval",
            "tier",
            "importance",
            "sensitivity",
            "agent_key",
            "notify",
            "exec_cmd",
            "webhook_url_secret",
            "webhook_key_secret",
            "circle",
            "retrievals",
            "last_retrieved_at",
            "last_run_at",
            "created_at",
            "updated_at",
        ]
        placeholders = ",".join("?" * len(cols))
        self.conn.execute(
            f"INSERT OR REPLACE INTO records ({','.join(cols)}) VALUES ({placeholders})",
            [rec.get(c) for c in cols],
        )
        self.conn.execute("DELETE FROM aliases WHERE key = ?", (rec["key"],))
        self.conn.execute("DELETE FROM tags WHERE key = ?", (rec["key"],))
        for a in aliases:
            a = a.strip().lower()
            if a:
                self.conn.execute(
                    "INSERT OR REPLACE INTO aliases(alias, key) VALUES (?, ?)",
                    (a, rec["key"]),
                )
        for t in tags:
            t = t.strip().lower()
            if t:
                self.conn.execute(
                    "INSERT OR IGNORE INTO tags(key, tag) VALUES (?, ?)",
                    (rec["key"], t),
                )
        if self._fts:
            self.conn.execute("DELETE FROM records_fts WHERE key = ?", (rec["key"],))
            self.conn.execute(
                "INSERT INTO records_fts(key, aliases, summary, tags, body) VALUES (?,?,?,?,?)",
                (
                    rec["key"],
                    " ".join(aliases),
                    rec.get("summary") or "",
                    " ".join(tags),
                    rec.get("body") or "",
                ),
            )

    def _load_relations_file(self) -> None:
        path = self.paths.relations
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            obj = json.loads(line)
            self.conn.execute(
                "INSERT OR REPLACE INTO relations(from_key, to_key, circle, note) VALUES (?,?,?,?)",
                (
                    obj["from"],
                    obj["to"],
                    obj.get("circle") or "work",
                    obj.get("note"),
                ),
            )

    def write_relations_file(self) -> None:
        rows = self.conn.execute(
            "SELECT from_key, to_key, circle, note FROM relations ORDER BY from_key, to_key"
        ).fetchall()
        lines = [
            json.dumps(
                {"from": r["from_key"], "to": r["to_key"], "circle": r["circle"], "note": r["note"] or ""},
                sort_keys=True,
            )
            + "\n"
            for r in rows
        ]
        self.paths.relations.parent.mkdir(parents=True, exist_ok=True)
        self.paths.relations.write_text("".join(lines), encoding="utf-8")

    def add_relation(self, src: str, dest: str, circle: str, note: str = "") -> None:
        if circle not in CIRCLE_WEIGHT:
            raise ValueError("circle must be family, friend, or work")
        self.conn.execute(
            "INSERT OR REPLACE INTO relations(from_key, to_key, circle, note) VALUES (?,?,?,?)",
            (src, dest, circle, note),
        )
        self.conn.commit()
        self.write_relations_file()

    def _visible_sql(
        self, agent: str | None, include_candidates: bool, archive: bool, table: str = ""
    ) -> tuple[str, list[Any]]:
        p = f"{table}." if table else ""
        clauses = []
        args: list[Any] = []
        if agent:
            clauses.append(f"({p}agent_key IS NULL OR {p}agent_key = ?)")
            args.append(agent)
        else:
            clauses.append(f"({p}agent_key IS NULL)")
        if not include_candidates:
            clauses.append(f"{p}kind != 'candidate'")
            clauses.append(f"{p}tier != 'candidate'")
        if not archive:
            cutoff = datetime.now(timezone.utc).timestamp() - EPISODIC_HIDE_DAYS * 86400
            cutoff_s = datetime.fromtimestamp(cutoff, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            clauses.append(
                f"({p}tier != 'episodic' OR coalesce({p}last_retrieved_at, {p}created_at, {p}updated_at) >= ?)"
            )
            args.append(cutoff_s)
        where = " AND ".join(clauses) if clauses else "1=1"
        return where, args

    def get(self, key: str, agent: str | None = None, bump: bool = True) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM records WHERE key = ?", (key,)).fetchone()
        if not row:
            alias = self.conn.execute(
                "SELECT key FROM aliases WHERE alias = ?", (key.lower(),)
            ).fetchone()
            if alias:
                row = self.conn.execute(
                    "SELECT * FROM records WHERE key = ?", (alias["key"],)
                ).fetchone()
        if not row:
            return None
        rec = dict(row)
        if rec.get("agent_key") and agent and rec["agent_key"] != agent:
            if rec["kind"] not in SHARED_KINDS:
                return None
        if bump:
            self.conn.execute(
                "UPDATE records SET retrievals = retrievals + 1, last_retrieved_at = ? WHERE key = ?",
                (_utcnow(), rec["key"]),
            )
            self.conn.commit()
            rec["retrievals"] = (rec["retrievals"] or 0) + 1
            rec["last_retrieved_at"] = _utcnow()
        rec["aliases"] = [
            r[0]
            for r in self.conn.execute(
                "SELECT alias FROM aliases WHERE key = ?", (rec["key"],)
            )
        ]
        rec["tags"] = [
            r[0]
            for r in self.conn.execute("SELECT tag FROM tags WHERE key = ?", (rec["key"],))
        ]
        return rec

    def log_miss(self, guessed: str) -> None:
        self.conn.execute(
            "INSERT INTO misses(guessed, at, resolved) VALUES (?,?,0)",
            (guessed, _utcnow()),
        )
        self.conn.commit()
        # write a candidate stub
        key = "miss." + hashlib.sha256(guessed.encode()).hexdigest()[:10]
        body = f"Looked for {guessed!r}, no hit. Add an alias or a new record. Do not invent a key."
        rec = {
            "key": key,
            "kind": "candidate",
            "domain": None,
            "summary": f"miss: {guessed}",
            "body": body,
            "path": None,
            "hash": None,
            "schedule": None,
            "timezone": None,
            "approval": "none",
            "tier": "candidate",
            "importance": 0.2,
            "sensitivity": "public",
            "agent_key": None,
            "notify": None,
            "exec_cmd": None,
            "webhook_url_secret": None,
            "webhook_key_secret": None,
            "circle": None,
            "retrievals": 0,
            "last_retrieved_at": None,
            "last_run_at": None,
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
        }
        path = write_markdown(self.paths.vault, rec, [guessed.lower()], ["miss"])
        rec["path"] = str(path.relative_to(self.paths.vault))
        rec["hash"] = _hash(path.read_text(encoding="utf-8"))
        self._upsert_record(rec, [guessed.lower()], ["miss"])
        self.conn.commit()

    def misses(self, unresolved: bool = True) -> list[dict[str, Any]]:
        q = "SELECT * FROM misses"
        if unresolved:
            q += " WHERE resolved = 0"
        q += " ORDER BY at DESC"
        return [dict(r) for r in self.conn.execute(q)]

    def _score(self, rec: dict[str, Any], now: datetime | None = None) -> float:
        now = now or datetime.now(timezone.utc)
        tw = TIER_WEIGHT.get(rec.get("tier") or "locked", 1.0)
        imp = float(rec.get("importance") or 1.0)
        ret = rec.get("retrievals") or 0
        recency = 1.0
        stamp = rec.get("last_retrieved_at") or rec.get("updated_at")
        if rec.get("tier") == "episodic" and stamp:
            try:
                dt = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                days = max(0.0, (now - dt).total_seconds() / 86400.0)
                recency = math.exp(-days / 30.0)
            except ValueError:
                recency = 0.5
        cw = CIRCLE_WEIGHT.get(rec.get("circle") or "", 1.0)
        return tw * imp * (1.0 + math.log1p(ret)) * recency * cw

    def search(
        self,
        q: str,
        agent: str | None = None,
        archive: bool = False,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        q = q.strip()
        if not q:
            return []
        # exact / alias first
        hit = self.get(q, agent=agent, bump=False)
        if hit and (archive or hit.get("tier") != "episodic" or True):
            if hit.get("kind") != "candidate" or archive:
                return [hit]
        where, args = self._visible_sql(agent, include_candidates=archive, archive=archive)
        rows: list[dict[str, Any]] = []
        if self._fts:
            try:
                fts = self.conn.execute(
                    "SELECT key FROM records_fts WHERE records_fts MATCH ? LIMIT 50",
                    (q,),
                ).fetchall()
                keys = [r[0] for r in fts]
                if keys:
                    ph = ",".join("?" * len(keys))
                    found = self.conn.execute(
                        f"SELECT * FROM records WHERE key IN ({ph}) AND {where}",
                        keys + args,
                    ).fetchall()
                    rows = [dict(r) for r in found]
            except sqlite3.OperationalError:
                rows = []
        if not rows:
            like = f"%{q.lower()}%"
            found = self.conn.execute(
                f"SELECT * FROM records WHERE {where} AND ("
                "lower(key) LIKE ? OR lower(ifnull(summary,'')) LIKE ? OR lower(body) LIKE ?)",
                args + [like, like, like],
            ).fetchall()
            rows = [dict(r) for r in found]
            # aliases
            alias_rows = self.conn.execute(
                "SELECT key FROM aliases WHERE alias LIKE ?", (like,)
            ).fetchall()
            extra_keys = [r[0] for r in alias_rows]
            have = {r["key"] for r in rows}
            for k in extra_keys:
                if k in have:
                    continue
                rec = self.conn.execute("SELECT * FROM records WHERE key = ?", (k,)).fetchone()
                if rec:
                    rows.append(dict(rec))
        for rec in rows:
            rec["_score"] = self._score(rec)
        rows.sort(key=lambda r: r["_score"], reverse=True)
        out = rows[:limit]
        if not out:
            self.log_miss(q)
        return out

    def query(
        self,
        *,
        domain: str | None = None,
        tag: str | None = None,
        kind: str | None = None,
        circle: str | None = None,
        agent: str | None = None,
        src: str | None = None,
        archive: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        where, args = self._visible_sql(
            agent, include_candidates=archive, archive=archive, table="r"
        )
        extra = []
        if domain:
            extra.append("r.domain = ?")
            args.append(domain)
        if kind:
            extra.append("r.kind = ?")
            args.append(kind)
        if circle:
            extra.append("r.circle = ?")
            args.append(circle)
        if extra:
            where = where + " AND " + " AND ".join(extra)
        sql = f"SELECT DISTINCT r.* FROM records r"
        if tag:
            sql += " JOIN tags t ON t.key = r.key"
            where += " AND t.tag = ?"
            args.append(tag.lower())
        sql += f" WHERE {where} LIMIT ?"
        args.append(limit)
        rows = [dict(r) for r in self.conn.execute(sql, args)]
        if src:
            rels = self.conn.execute(
                "SELECT to_key FROM relations WHERE from_key = ?"
                + (" AND circle = ?" if circle else ""),
                (src, circle) if circle else (src,),
            ).fetchall()
            allow = {r[0] for r in rels}
            rows = [r for r in rows if r["key"] in allow]
        for rec in rows:
            rec["_score"] = self._score(rec)
            rec["aliases"] = [
                a[0]
                for a in self.conn.execute(
                    "SELECT alias FROM aliases WHERE key = ?", (rec["key"],)
                )
            ]
            rec["tags"] = [
                a[0]
                for a in self.conn.execute("SELECT tag FROM tags WHERE key = ?", (rec["key"],))
            ]
        rows.sort(key=lambda r: r["_score"], reverse=True)
        return rows

    def jobs(self) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM records WHERE kind = 'job' AND schedule IS NOT NULL AND schedule != ''"
            )
        ]

    def stamp_last_run(self, key: str, when: str | None = None) -> None:
        self.conn.execute(
            "UPDATE records SET last_run_at = ? WHERE key = ?",
            (when or _utcnow(), key),
        )
        self.conn.commit()

    def set_record(self, rec: dict[str, Any], aliases: list[str], tags: list[str]) -> Path:
        kind = rec.get("kind") or "policy"
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind}")
        rec.setdefault("tier", "candidate" if kind == "candidate" else "locked")
        rec.setdefault("approval", "none")
        rec.setdefault("importance", 1.0)
        rec.setdefault("sensitivity", "public")
        rec.setdefault("retrievals", 0)
        rec.setdefault("created_at", _utcnow())
        rec["updated_at"] = _utcnow()
        reason = looks_like_raw_secret(rec.get("body") or "")
        if reason:
            raise ValueError(reason)
        if rec.get("sensitivity") == "private":
            rec["path"] = None  # record_path will nest under private
        path = write_markdown(self.paths.vault, rec, aliases, tags)
        rec["path"] = str(path.relative_to(self.paths.vault))
        rec["hash"] = _hash(path.read_text(encoding="utf-8"))
        existing = self.conn.execute(
            "SELECT retrievals, last_retrieved_at, last_run_at, created_at FROM records WHERE key = ?",
            (rec["key"],),
        ).fetchone()
        if existing:
            rec["retrievals"] = existing["retrievals"]
            rec["last_retrieved_at"] = existing["last_retrieved_at"]
            rec["last_run_at"] = existing["last_run_at"]
            rec["created_at"] = existing["created_at"]
        self._upsert_record(rec, aliases, tags)
        self.conn.commit()
        return path

    def accept(self, key: str) -> Path:
        rec = self.get(key, bump=False)
        if not rec:
            raise KeyError(key)
        old_path = self.paths.vault / rec["path"] if rec.get("path") else None
        rec["kind"] = rec["kind"] if rec["kind"] != "candidate" else "policy"
        rec["tier"] = "locked"
        path = self.set_record(rec, rec.get("aliases") or [], rec.get("tags") or [])
        if old_path and old_path.exists() and old_path.resolve() != path.resolve():
            old_path.unlink()
        return path

    def dump_records(self, public: bool = False) -> list[dict[str, Any]]:
        rows = [dict(r) for r in self.conn.execute("SELECT * FROM records ORDER BY key")]
        out = []
        for rec in rows:
            if public and rec.get("sensitivity") == "private":
                continue
            rec["aliases"] = [
                a[0]
                for a in self.conn.execute(
                    "SELECT alias FROM aliases WHERE key = ?", (rec["key"],)
                )
            ]
            rec["tags"] = [
                a[0]
                for a in self.conn.execute("SELECT tag FROM tags WHERE key = ?", (rec["key"],))
            ]
            out.append(rec)
        return out

    def import_records(self, items: Iterable[dict[str, Any]]) -> int:
        n = 0
        for rec in items:
            aliases = _as_list(rec.pop("aliases", []))
            tags = _as_list(rec.pop("tags", []))
            rec.pop("_score", None)
            self.set_record(rec, aliases, tags)
            n += 1
        return n

    def consolidate(self, now: datetime | None = None) -> dict[str, list[str]]:
        """Demote cold working → episodic. List hot candidates. Never edit CORE."""
        now = now or datetime.now(timezone.utc)
        cutoff = now.timestamp() - 14 * 86400
        cutoff_s = datetime.fromtimestamp(cutoff, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        demoted = []
        rows = self.conn.execute(
            "SELECT * FROM records WHERE kind = 'working' OR tier = 'working'"
        ).fetchall()
        for row in rows:
            rec = dict(row)
            stamp = rec.get("last_retrieved_at") or rec.get("updated_at") or ""
            if stamp and stamp < cutoff_s:
                rec["kind"] = "episodic"
                rec["tier"] = "episodic"
                aliases = [
                    a[0]
                    for a in self.conn.execute(
                        "SELECT alias FROM aliases WHERE key = ?", (rec["key"],)
                    )
                ]
                tags = [
                    a[0]
                    for a in self.conn.execute(
                        "SELECT tag FROM tags WHERE key = ?", (rec["key"],)
                    )
                ]
                self.set_record(rec, aliases, tags)
                demoted.append(rec["key"])
        hot = []
        cands = self.conn.execute(
            "SELECT * FROM records WHERE tier = 'candidate' AND retrievals >= 3"
        ).fetchall()
        for row in cands:
            hot.append(row["key"])
        return {"demoted": demoted, "hot_candidates": hot}
