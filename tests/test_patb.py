import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from patb.cli import main
from patb.core import core_text
from patb.paths import Paths
from patb.secrets import looks_like_raw_secret, set_secret
from patb.store import Store, content_tokens
from patb.tick import due_jobs, fire_job, tick


class PatbTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        os.environ["PATB_HOME"] = str(self.home)
        os.environ.pop("PATB_VAULT", None)
        os.environ.pop("PATB_AGENT", None)
        self.paths = Paths(self.home)
        self.paths.ensure_home()

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("PATB_HOME", None)

    def run_cli(self, *argv, stdin=""):
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(stdin)):
            with mock.patch("sys.stdout", buf_out), mock.patch("sys.stderr", buf_err):
                code = main(["--home", str(self.home), *argv])
        return code, buf_out.getvalue(), buf_err.getvalue()

    def test_set_get_alias_search(self):
        code, out, err = self.run_cli(
            "set",
            "email.usps",
            "--kind",
            "policy",
            "--domain",
            "email",
            "--alias",
            "usps",
            "--alias",
            "informed delivery",
            "--tag",
            "silent-delete",
            "--summary",
            "Trash USPS",
            "--body",
            "Trash USPS Informed Delivery. Do not mention it.",
        )
        self.assertEqual(code, 0, err)
        code, out, err = self.run_cli("get", "email.usps")
        self.assertEqual(code, 0, err)
        self.assertIn("Trash USPS", out)
        code, out, err = self.run_cli("get", "informed delivery")
        self.assertEqual(code, 0, err)
        self.assertIn("Trash USPS", out)
        code, out, err = self.run_cli("search", "family link")  # miss
        self.assertEqual(code, 1)
        code, out, err = self.run_cli("query", "--domain", "email", "--tag", "silent-delete")
        self.assertEqual(code, 0, err)
        self.assertIn("email.usps", out)

    def test_reject_raw_webhook(self):
        code, _, err = self.run_cli(
            "set",
            "agent.bad",
            "--kind",
            "agent",
            "--body",
            "https://api2.cursor.sh/automations/webhook/abc123secret",
        )
        self.assertEqual(code, 2)
        self.assertIn("secret", err.lower())

    def test_secret_expand_not_in_dump(self):
        set_secret(self.paths, "HOME_ADDRESS", "123 Secret Lane")
        self.run_cli(
            "set",
            "identity.user",
            "--kind",
            "identity",
            "--body",
            "Home: ${HOME_ADDRESS}",
        )
        code, out, _ = self.run_cli("get", "identity.user")
        self.assertEqual(code, 0)
        self.assertIn("123 Secret Lane", out)
        code, out, _ = self.run_cli("dump")
        self.assertEqual(code, 0)
        self.assertNotIn("123 Secret Lane", out)
        self.assertIn("${HOME_ADDRESS}", out)

    def test_reindex_from_vault(self):
        self.run_cli(
            "set",
            "email.usps",
            "--kind",
            "policy",
            "--alias",
            "usps",
            "--body",
            "Trash it.",
        )
        db = self.paths.sqlite
        db.unlink()
        store = Store(self.paths)
        n = store.reindex()
        self.assertGreaterEqual(n, 1)
        rec = store.get("usps", bump=False)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["key"], "email.usps")

    def test_dump_import(self):
        self.run_cli("set", "email.usps", "--body", "Trash it.")
        dump_path = self.home / "d.jsonl"
        self.run_cli("dump", "-o", str(dump_path))
        other = Path(tempfile.mkdtemp())
        os.environ["PATB_HOME"] = str(other)
        try:
            code, out, err = self.run_cli("--home", str(other), "import", str(dump_path))
            self.assertEqual(code, 0, err)
            code, out, err = self.run_cli("--home", str(other), "get", "email.usps")
            self.assertEqual(code, 0, err)
            self.assertIn("Trash it", out)
        finally:
            os.environ["PATB_HOME"] = str(self.home)

    def test_agent_scope(self):
        self.run_cli(
            "set",
            "working.inbox.open",
            "--kind",
            "working",
            "--tier",
            "working",
            "--agent-key",
            "agent.inbox",
            "--body",
            "open item A",
        )
        code, out, _ = self.run_cli("--agent", "agent.inbox", "get", "working.inbox.open")
        self.assertEqual(code, 0)
        code, out, err = self.run_cli("--agent", "agent.github", "get", "working.inbox.open")
        self.assertEqual(code, 1)

    def test_accept(self):
        self.run_cli(
            "propose",
            "email.newthing",
            "--kind",
            "candidate",
            "--body",
            "do this",
        )
        code, _, err = self.run_cli("accept", "email.newthing")
        self.assertEqual(code, 0, err)
        store = Store(self.paths)
        rec = store.get("email.newthing", bump=False)
        self.assertEqual(rec["tier"], "locked")

    def test_tick_lock_and_due(self):
        store = Store(self.paths)
        store.set_record(
            {
                "key": "job.hourly.mail",
                "kind": "job",
                "body": "scan",
                "schedule": "* * * * *",
                "notify": "webhook",
                "webhook_url_secret": "WH_URL",
                "webhook_key_secret": "WH_KEY",
                "tier": "locked",
            },
            [],
            [],
        )
        set_secret(self.paths, "WH_URL", "https://example.test/hook")
        set_secret(self.paths, "WH_KEY", "s3cret")
        posts = []

        def poster(url, headers, body):
            posts.append((url, headers, body))
            return 200, "ok"

        when = datetime(2026, 8, 30, 10, 5, tzinfo=timezone.utc)
        jobs = due_jobs(store, when=when)
        self.assertEqual(len(jobs), 1)
        result = tick(self.paths, store, when=when, poster=poster)
        self.assertEqual(len(result["fired"]), 1)
        self.assertTrue(result["fired"][0]["ok"])
        self.assertEqual(len(posts), 1)
        self.assertIn(b"job.hourly.mail", posts[0][2])
        # second tick same minute: last_run set, should not fire
        result2 = tick(self.paths, store, when=when, poster=poster)
        self.assertEqual(result2["fired"], [])

    def test_tick_nothing_due_no_http(self):
        store = Store(self.paths)
        store.set_record(
            {
                "key": "job.hourly.mail",
                "kind": "job",
                "body": "scan",
                "schedule": "0 * * * *",
                "notify": "webhook",
                "webhook_url_secret": "WH_URL",
                "tier": "locked",
            },
            [],
            [],
        )
        posts = []

        def poster(url, headers, body):
            posts.append(1)
            return 200, "ok"

        when = datetime(2026, 8, 30, 10, 5, tzinfo=timezone.utc)  # minute != 0
        result = tick(self.paths, store, when=when, poster=poster)
        self.assertEqual(result["fired"], [])
        self.assertEqual(posts, [])

    def test_consolidate_does_not_touch_core(self):
        core_before = core_text()
        self.run_cli(
            "set",
            "working.old",
            "--kind",
            "working",
            "--tier",
            "working",
            "--body",
            "stale",
        )
        store = Store(self.paths)
        store.conn.execute(
            "UPDATE records SET updated_at = '2020-01-01T00:00:00Z', last_retrieved_at = '2020-01-01T00:00:00Z' WHERE key = 'working.old'"
        )
        store.conn.commit()
        result = store.consolidate()
        self.assertIn("working.old", result["demoted"])
        rec = store.get("working.old", bump=False)
        self.assertEqual(rec["tier"], "episodic")
        self.assertEqual(core_text(), core_before)

    def test_audit_clean(self):
        self.run_cli("set", "email.usps", "--body", "Trash it.")
        code, out, err = self.run_cli("audit")
        self.assertEqual(code, 0, err)

    def test_core_check(self):
        code, out, _ = self.run_cli("core")
        self.assertEqual(code, 0)
        self.assertIn("patb CORE", out)
        self.assertNotIn("Brain", out)
        self.assertIn("2-4 keywords", out)
        self.assertIn("not the whole utterance", out)
        code, out, _ = self.run_cli("core", "--check")
        self.assertEqual(code, 0)

    def test_search_keywords_not_whole_utterance(self):
        self.run_cli(
            "set",
            "identity.vehicle.cadenza",
            "--kind",
            "identity",
            "--alias",
            "cadenza",
            "--alias",
            "tires",
            "--alias",
            "tire size",
            "--alias",
            "my car",
            "--summary",
            "Kia Cadenza tires",
            "--body",
            "Kia Cadenza. Tire size 245/40R19 94V.",
        )
        for q in (
            "cadenza",
            "tire size",
            "tires",
            "what size were those tires on the cadenza?",
            "I can't remember the tire size on my car, do you remember?",
        ):
            code, out, err = self.run_cli("search", q)
            self.assertEqual(code, 0, f"{q!r} missed: {err}")
            self.assertIn("identity.vehicle.cadenza", out)

        code, out, err = self.run_cli("search", "what is the weather in paris today")
        self.assertEqual(code, 1)
        self.assertIn("no hits", err)

    def test_content_tokens_drop_filler(self):
        self.assertEqual(
            content_tokens("what size were those tires on the cadenza?"),
            ["size", "tires", "cadenza"],
        )
        self.assertEqual(
            content_tokens("I can't remember the tire size on my car, do you remember?"),
            ["tire", "size", "car"],
        )

    def test_search_utterance_without_english_aliases(self):
        self.run_cli(
            "set",
            "identity.vehicle.cadenza",
            "--kind",
            "identity",
            "--alias",
            "cadenza",
            "--body",
            "Kia Cadenza. Tire size 245/40R19 94V.",
        )
        code, out, err = self.run_cli(
            "search", "what size were those tires on the cadenza?"
        )
        self.assertEqual(code, 0, err)
        self.assertIn("identity.vehicle.cadenza", out)

    def test_looks_like_secret(self):
        self.assertIsNotNone(
            looks_like_raw_secret("https://api2.cursor.sh/automations/webhook/xyz")
        )
        self.assertIsNone(looks_like_raw_secret("use ${AGENT_INBOX_WEBHOOK_URL}"))


if __name__ == "__main__":
    unittest.main()
