import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cold_workspace import ColdWorkspaceError, clone_candidate, env_for_checks


class ColdWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.git(self.source, "init", "-q", "-b", "main")
        self.git(self.source, "config", "user.name", "Fixture")
        self.git(self.source, "config", "user.email", "fixture@example.invalid")
        (self.source / ".gitignore").write_text("private.flag\n", encoding='utf-8')
        (self.source / "module.py").write_text("value = 1\n", encoding='utf-8')
        self.git(self.source, "add", ".")
        self.git(self.source, "commit", "-qm", "base")
        self.base = self.git(self.source, "rev-parse", "HEAD")
        (self.source / "module.py").write_text("value = 2\n", encoding='utf-8')
        self.git(self.source, "commit", "-qam", "candidate")
        self.head = self.git(self.source, "rev-parse", "HEAD")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, directory, *args):
        return subprocess.check_output(["git", "-C", str(directory), *args],
                                       text=True, stderr=subprocess.PIPE, encoding='utf-8').strip()

    def test_checkout_is_exact_independent_and_has_no_builder_artifacts(self):
        (self.source / "private.flag").write_text("builder state", encoding='utf-8')
        (self.source / "transcript.txt").write_text("untracked transcript", encoding='utf-8')
        (self.source / "module.py").write_text("uncommitted builder change", encoding='utf-8')
        destination = clone_candidate(self.source, self.root / "verifier", self.head, self.base)
        self.assertTrue((destination / ".git").is_dir())
        self.assertEqual(self.git(destination, "rev-parse", "HEAD"), self.head)
        self.assertEqual(self.git(destination, "rev-parse", "--git-common-dir"), ".git")
        self.assertEqual(self.git(destination, "status", "--porcelain"), "")
        self.assertEqual(self.git(destination, "remote"), "")
        self.assertFalse((destination / "private.flag").exists())
        self.assertFalse((destination / "transcript.txt").exists())
        self.assertEqual((destination / "module.py").read_text(encoding='utf-8'), "value = 2\n")
        self.assertFalse((destination / ".git/objects/info/alternates").exists())
        source_inodes = {(p.stat().st_dev, p.stat().st_ino)
                         for p in (self.source / ".git/objects").rglob("*") if p.is_file()}
        for p in (destination / ".git/objects").rglob("*"):
            if p.is_file():
                self.assertNotIn((p.stat().st_dev, p.stat().st_ino), source_inodes)

    def test_source_hooks_and_configuration_are_not_copied_or_executed(self):
        hooks = self.root / "hooks"
        hooks.mkdir()
        sentinel = self.root / "hook-ran"
        hook = hooks / "post-checkout"
        hook.write_text("#!/bin/sh\ntouch '" + str(sentinel) + "'\n", encoding='utf-8')
        hook.chmod(0o755)
        self.git(self.source, "config", "core.hooksPath", str(hooks))
        self.git(self.source, "config", "factory.private", "private-value")
        destination = clone_candidate(self.source, self.root / "verifier", self.head, self.base)
        self.assertFalse(sentinel.exists())
        config = self.git(destination, "config", "--local", "--list")
        self.assertNotIn("private-value", config)
        self.assertNotIn(str(hooks), config)
        self.assertFalse((destination / ".git/hooks/post-checkout").exists())

    def test_reject_existing_destination_without_removing_work(self):
        destination = self.root / "existing"
        destination.mkdir()
        keep = destination / "keep"
        keep.write_text("user work", encoding='utf-8')
        with self.assertRaises(ColdWorkspaceError):
            clone_candidate(self.source, destination, self.head, self.base)
        self.assertEqual(keep.read_text(encoding='utf-8'), "user work")

    def test_reject_non_ancestor_base(self):
        self.git(self.source, "checkout", "--orphan", "unrelated")
        self.git(self.source, "commit", "-qm", "unrelated")
        unrelated = self.git(self.source, "rev-parse", "HEAD")
        with self.assertRaises(ColdWorkspaceError):
            clone_candidate(self.source, self.root / "verifier", self.head, unrelated)

    def test_reject_unpinned_refs(self):
        with self.assertRaises(ColdWorkspaceError):
            clone_candidate(self.source, self.root / "verifier", "HEAD", self.base)

    def test_timeout_fails_closed(self):
        with patch("cold_workspace.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 120)):
            with self.assertRaises(ColdWorkspaceError):
                clone_candidate(self.source, self.root / "verifier", self.head, self.base)

    def test_environments_are_fresh_private_and_omit_secrets(self):
        with patch.dict(os.environ, {"API_KEY": "secret", "GH_TOKEN": "secret",
                                   "GIT_DIR": "bad", "PYTHONPATH": "bad",
                                   "CLAUDE_CODE_SESSION_ID": "builder-session"}):
            first = env_for_checks(self.root / "verifier", "ticket/first")
            second = env_for_checks(self.root / "verifier", "ticket/first")
        for key in ("API_KEY", "GH_TOKEN", "GIT_DIR", "PYTHONPATH", "CLAUDE_CODE_SESSION_ID"):
            self.assertNotIn(key, first)
        self.assertNotEqual(first["HOME"], second["HOME"])
        self.assertEqual(first["FACTORY_NAMESPACE"], "ticket/first")
        self.assertEqual(Path(first["HOME"]).parent, self.root)
        self.assertTrue(Path(first["TMPDIR"]).is_dir())
        if os.name == "posix":
            self.assertEqual(Path(first["HOME"]).stat().st_mode & 0o777, 0o700)

    def test_ambient_git_config_cannot_redirect_checkout(self):
        bad_config = self.root / "bad-global"
        bad_config.write_text("[init]\n templateDir = /nonexistent\n", encoding='utf-8')
        with patch.dict(os.environ, {"GIT_DIR": "/bad", "GIT_WORK_TREE": "/bad",
                                   "GIT_CONFIG_GLOBAL": str(bad_config)}):
            destination = clone_candidate(self.source, self.root / "verifier", self.head, self.base)
        self.assertEqual(self.git(destination, "rev-parse", "HEAD"), self.head)


if __name__ == "__main__":
    unittest.main()
