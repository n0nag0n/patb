"""OS tick: no LLM. Fire due jobs via webhook or exec. flock so overlapping ticks no-op."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from patb.cronexpr import CronError, matches
from patb.guard import GuardError, check_webhook_url, exec_argv
from patb.paths import Paths
from patb.secrets import load
from patb.store import Store

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore


Poster = Callable[[str, dict[str, str], bytes], tuple[int, str]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.HTTPError(req.full_url, code, "redirect disallowed", headers, fp)


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirect)


def _now_in(tz_name: str | None) -> datetime:
    if tz_name:
        try:
            return datetime.now(ZoneInfo(tz_name))
        except ZoneInfoNotFoundError:
            pass
    return datetime.now().astimezone()


def acquire_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a", encoding="utf-8")
    if fcntl is None:
        return fh
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def _default_poster(url: str, headers: dict[str, str], body: bytes) -> tuple[int, str]:
    err = check_webhook_url(url, resolve_host=True)
    if err:
        return 0, err
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with _NO_REDIRECT_OPENER.open(req, timeout=8) as resp:
            return resp.status, resp.read()[:200].decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, str(exc.reason)
    except urllib.error.URLError as exc:
        return 0, str(exc.reason)


def _secret_map(store: Store, rec: dict[str, Any], secrets: dict[str, str]) -> tuple[str | None, str | None]:
    url_name = rec.get("webhook_url_secret")
    key_name = rec.get("webhook_key_secret")
    if rec.get("kind") == "job" and rec.get("agent_key"):
        agent = store.get(rec["agent_key"], bump=False)
        if agent:
            url_name = url_name or agent.get("webhook_url_secret")
            key_name = key_name or agent.get("webhook_key_secret")
    url = secrets.get(url_name) if url_name else None
    token = secrets.get(key_name) if key_name else None
    return url, token


def due_jobs(store: Store, when: datetime | None = None) -> list[dict[str, Any]]:
    out = []
    for job in store.jobs():
        expr = job.get("schedule") or ""
        try:
            local = when or _now_in(job.get("timezone"))
            if when and job.get("timezone"):
                try:
                    local = when.astimezone(ZoneInfo(job["timezone"]))
                except ZoneInfoNotFoundError:
                    local = when
        except CronError:
            continue
        try:
            if not matches(expr, local):
                continue
        except CronError:
            continue
        last = job.get("last_run_at")
        window = local.replace(second=0, microsecond=0)
        if last:
            try:
                last_dt = datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if last_dt.astimezone(local.tzinfo) >= window:
                    continue
            except ValueError:
                pass
        out.append(job)
    return out


def fire_job(
    store: Store,
    job: dict[str, Any],
    secrets: dict[str, str],
    poster: Poster | None = None,
    when: datetime | None = None,
) -> dict[str, Any]:
    poster = poster or _default_poster
    notify = job.get("notify") or "webhook"
    payload = json.dumps({"key": job["key"]}).encode("utf-8")
    stamp = (
        when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if when is not None
        else None
    )
    store.stamp_last_run(job["key"], stamp)
    if notify == "exec":
        cmd = job.get("exec_cmd") or ""
        try:
            argv = exec_argv(cmd)
        except GuardError as exc:
            return {"key": job["key"], "ok": False, "error": str(exc)}
        try:
            env = os.environ.copy()
            env["PATB_JOB_KEY"] = job["key"]
            env["PATB_HOME"] = str(store.paths.home)
            src = str(Path(__file__).resolve().parents[1])
            env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
            proc = subprocess.run(
                argv,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )
            return {
                "key": job["key"],
                "ok": proc.returncode == 0,
                "status": proc.returncode,
                "notify": "exec",
            }
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"key": job["key"], "ok": False, "error": str(exc)}
    url, token = _secret_map(store, job, secrets)
    if not url:
        return {"key": job["key"], "ok": False, "error": "missing webhook url secret"}
    url_err = check_webhook_url(url, resolve_host=False)
    if url_err:
        return {"key": job["key"], "ok": False, "error": url_err}
    headers = {"content-type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-Automation-Key"] = token
    status, msg = poster(url, headers, payload)
    return {
        "key": job["key"],
        "ok": 200 <= status < 300,
        "status": status,
        "notify": "webhook",
        "detail": msg,
    }


def tick(
    paths: Paths,
    store: Store,
    when: datetime | None = None,
    poster: Poster | None = None,
) -> dict[str, Any]:
    lock = acquire_lock(paths.tick_lock)
    if lock is None:
        return {"skipped": "locked", "fired": []}
    try:
        jobs = due_jobs(store, when=when)
        secrets = load(paths.secrets)
        fired = [fire_job(store, job, secrets, poster=poster, when=when) for job in jobs]
        return {"skipped": None, "fired": fired}
    finally:
        lock.close()


def crontab_line(patb_bin: str) -> str:
    if any(ch in patb_bin for ch in "\n\r"):
        raise RuntimeError("invalid patb bin path")
    return f"* * * * * {shlex.quote(patb_bin)} tick >/dev/null 2>&1"


def install_crontab(patb_bin: str) -> str:
    line = crontab_line(patb_bin)
    try:
        current = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, check=False
        )
        body = current.stdout if current.returncode == 0 else ""
    except FileNotFoundError as exc:
        raise RuntimeError("crontab not available") from exc
    if line in body.splitlines():
        return "already installed"
    if body and not body.endswith("\n"):
        body += "\n"
    body += line + "\n"
    proc = subprocess.run(["crontab", "-"], input=body, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or "crontab install failed")
    return "installed"


def uninstall_crontab(patb_bin: str) -> str:
    line = crontab_line(patb_bin)
    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    if current.returncode != 0:
        return "no crontab"
    lines = [ln for ln in current.stdout.splitlines() if ln.strip() != line]
    new = "\n".join(lines) + ("\n" if lines else "")
    proc = subprocess.run(["crontab", "-"], input=new, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or "crontab uninstall failed")
    return "removed"
