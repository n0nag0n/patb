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
from patb.cli import build_parser
from patb.secrets import looks_like_raw_secret, names_missing_placeholder, set_secret
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

    def test_core_md_matches_baked_text(self):
        from patb.core import CORE_TEXT, core_text

        baked = CORE_TEXT if CORE_TEXT.endswith("\n") else CORE_TEXT + "\n"
        self.assertEqual(core_text(), baked)

    def test_core_standing_write_instruction(self):
        code, out, err = self.run_cli("core")
        self.assertEqual(code, 0, err)
        self.assertIn("patb CORE 0.1.5", out)
        self.assertIn("patb get protocol.global", out)
        self.assertIn("If it misses, continue", out)
        self.assertIn("When a standing rule changes", out)
        self.assertIn("patb propose", out)
        self.assertIn("patb set", out)
        self.assertIn("Do not append it to CORE", out)
        self.assertIn("agent profile file", out)
        self.assertIn("2-4 keywords", out)
        self.assertIn("numbered list", out)
        self.assertIn("patb secret set", out)
        self.assertIn("There is no `patb secret get`", out)
        self.assertIn("Retrieve is `patb get`", out)
        self.assertIn("search working records first", out)
        self.assertEqual(out.count("numbered list"), 1)
        self.assertNotIn("patb secret get NAME", out)

    def test_vault_example_protocol_global(self):
        from patb.paths import repo_root

        path = repo_root() / "vault.example" / "protocols" / "global.md"
        self.assertTrue(path.is_file(), path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("key: protocol.global", text)
        lowered = text.lower()
        for banned in ("family-first", "sky9", "hsa", "usps"):
            self.assertNotIn(banned, lowered)

    def test_protocol_global_miss_is_quiet(self):
        self.assertFalse((self.paths.vault / "protocols" / "global.md").exists())
        code, out, err = self.run_cli("get", "protocol.global")
        self.assertEqual(code, 1)
        self.assertIn("not found", err)
        self.assertFalse((self.paths.vault / "protocols" / "global.md").exists())
        store = Store(self.paths)
        guessed = [m["guessed"] for m in store.misses()]
        self.assertNotIn("protocol.global", guessed)
        code, _, _ = self.run_cli("get", "email.usps")
        self.assertEqual(code, 1)
        store = Store(self.paths)
        guessed = [m["guessed"] for m in store.misses()]
        self.assertIn("email.usps", guessed)
        self.assertNotIn("protocol.global", guessed)

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

    def test_get_warns_named_secret_without_placeholder(self):
        set_secret(self.paths, "EXAMPLE_PHONE", "555-0100")
        self.run_cli(
            "set",
            "working.example.household",
            "--kind",
            "working",
            "--tier",
            "working",
            "--body",
            "Phone is patb secret EXAMPLE_PHONE",
        )
        code, out, err = self.run_cli("get", "working.example.household")
        self.assertEqual(code, 0, err)
        self.assertIn("warn:", err)
        self.assertIn("EXAMPLE_PHONE", err)
        self.assertIn("${EXAMPLE_PHONE}", err)
        self.assertIn("cannot print", err)
        self.assertIn("do not open secrets.env", err)
        self.assertIn("Phone is patb secret EXAMPLE_PHONE", out)
        self.assertNotIn("555-0100", out)
        self.assertNotIn("555-0100", err)

    def test_get_expands_placeholder_without_warn(self):
        set_secret(self.paths, "EXAMPLE_PHONE", "555-0100")
        self.run_cli(
            "set",
            "working.example.household",
            "--kind",
            "working",
            "--tier",
            "working",
            "--body",
            "Phone: ${EXAMPLE_PHONE}",
        )
        code, out, err = self.run_cli("get", "working.example.household")
        self.assertEqual(code, 0, err)
        self.assertNotIn("warn:", err)
        self.assertIn("555-0100", out)
        self.assertNotIn("${EXAMPLE_PHONE}", out)

    def test_search_and_query_full_do_not_expand_secrets(self):
        set_secret(self.paths, "EXAMPLE_PHONE", "555-0100")
        self.run_cli(
            "set",
            "working.example.household",
            "--kind",
            "working",
            "--tier",
            "working",
            "--alias",
            "cedar household",
            "--tag",
            "cedar",
            "--body",
            "Phone: ${EXAMPLE_PHONE}",
        )
        code, out, err = self.run_cli("search", "cedar household", "--full")
        self.assertEqual(code, 0, err)
        self.assertIn("${EXAMPLE_PHONE}", out)
        self.assertNotIn("555-0100", out)
        self.assertNotIn("555-0100", err)
        code, out, err = self.run_cli("--json", "search", "cedar household", "--full")
        self.assertEqual(code, 0, err)
        self.assertIn("${EXAMPLE_PHONE}", out)
        self.assertNotIn("555-0100", out)
        code, out, err = self.run_cli("query", "--kind", "working", "--full")
        self.assertEqual(code, 0, err)
        self.assertIn("${EXAMPLE_PHONE}", out)
        self.assertNotIn("555-0100", out)
        code, out, err = self.run_cli("--json", "query", "--kind", "working", "--full")
        self.assertEqual(code, 0, err)
        self.assertIn("${EXAMPLE_PHONE}", out)
        self.assertNotIn("555-0100", out)

    def test_no_secret_get_subcommand(self):
        set_secret(self.paths, "EXAMPLE_PHONE", "555-0100")
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", buf_out), mock.patch("sys.stderr", buf_err):
            with self.assertRaises(SystemExit) as cm:
                main(["--home", str(self.home), "secret", "get", "EXAMPLE_PHONE"])
        self.assertNotEqual(cm.exception.code, 0)
        combined = buf_out.getvalue() + buf_err.getvalue()
        self.assertNotIn("555-0100", combined)
        secret_parser = None
        for action in build_parser()._subparsers._group_actions:
            choices = getattr(action, "choices", None) or {}
            if "secret" in choices:
                secret_parser = choices["secret"]
                break
        self.assertIsNotNone(secret_parser)
        secret_subs = []
        for action in secret_parser._subparsers._group_actions:
            secret_subs.extend((getattr(action, "choices", None) or {}).keys())
        self.assertIn("set", secret_subs)
        self.assertNotIn("get", secret_subs)
        self.assertNotIn("list", secret_subs)

    def test_names_missing_placeholder_limits_false_positives(self):
        body = "Phone is patb secret EXAMPLE_PHONE. Also OTHER_TOKEN and ${HOME_ADDRESS}."
        self.assertEqual(
            names_missing_placeholder(body, ["HOME_ADDRESS", "EXAMPLE_PHONE"]),
            ["EXAMPLE_PHONE"],
        )
        self.assertEqual(names_missing_placeholder("Call OTHER_TOKEN later", ["EXAMPLE_PHONE"]), [])
        self.assertEqual(
            names_missing_placeholder("Phone is patb secret EXAMPLE_PHONE", []),
            ["EXAMPLE_PHONE"],
        )
        self.assertEqual(
            names_missing_placeholder("Call EXAMPLE_PHONE tonight", ["EXAMPLE_PHONE"]),
            ["EXAMPLE_PHONE"],
        )
        self.assertEqual(names_missing_placeholder("Phone: ${EXAMPLE_PHONE}", ["EXAMPLE_PHONE"]), [])

    def test_vault_example_household_pattern(self):
        from patb.paths import repo_root

        root = repo_root() / "vault.example"
        protocol = (root / "protocols" / "household.pick.md").read_text(encoding="utf-8")
        working = (
            root / "working" / "shared" / "working.example.household.md"
        ).read_text(encoding="utf-8")
        self.assertIn("key: protocol.household.pick", protocol)
        self.assertIn("Search working notes for the live list", protocol)
        self.assertIn("not the roster", protocol.lower())
        self.assertNotIn("Alex Cedar", protocol)
        self.assertIn("key: working.example.household", working)
        self.assertIn("${EXAMPLE_PHONE}", working)
        self.assertIn("alex", working.lower())
        self.assertIn("sam", working.lower())
        self.assertIn("cedar", working.lower())
        self.assertIn("tags:", working)
        self.assertIn("aliases:", working)
        for path in root.rglob("*.md"):
            text = path.read_text(encoding="utf-8").lower()
            self.assertNotIn("sky9", text, path)
            self.assertNotIn("patb secret get", text.replace("there is no `patb secret get`", ""))


if __name__ == "__main__":
    unittest.main()
