import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import bootstrap_dependencies as dependencies


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.origin = self.base / "upstream"
        self.origin.mkdir()
        self.git(self.origin, "init", "--quiet")
        self.git(self.origin, "config", "user.name", "Test Author")
        self.git(self.origin, "config", "user.email", "test@example.invalid")
        (self.origin / "version.txt").write_text("pinned\n")
        self.git(self.origin, "add", ".")
        self.git(self.origin, "commit", "--quiet", "-m", "Pinned revision")
        self.revision = self.git(self.origin, "rev-parse", "HEAD")
        (self.origin / "version.txt").write_text("newer\n")
        self.git(self.origin, "commit", "--quiet", "-am", "Newer revision")
        self.archive = self.base / "archive"
        self.archive.mkdir()
        self.configure(self.archive)
        pins = patch.object(dependencies, "DEPENDENCY_REVISIONS", {"library": self.revision})
        pins.start()
        self.addCleanup(pins.stop)

    def git(self, root, *args):
        return dependencies.git(root, *args)

    def configure(self, root):
        self.git(root, "config", "--file", str(root / ".gitmodules"), "submodule.library.path", "library")
        self.git(root, "config", "--file", str(root / ".gitmodules"), "submodule.library.url", str(self.origin))

    def test_archive_fetches_exact_pin_and_is_repeatable(self):
        (self.archive / "library").mkdir()
        dependencies.bootstrap(self.archive)
        dependencies.bootstrap(self.archive)
        target = self.archive / "library"
        self.assertEqual(self.git(target, "rev-parse", "HEAD"), self.revision)
        self.assertEqual((target / "version.txt").read_text(), "pinned\n")
        self.assertFalse((self.archive / ".git").exists())

    def test_archive_inside_another_repository(self):
        self.git(self.base, "init", "--quiet")
        dependencies.bootstrap(self.archive)
        self.assertEqual(self.git(self.archive / "library", "rev-parse", "HEAD"), self.revision)
        self.assertFalse((self.archive / ".git").exists())

    def test_nonempty_directory_is_not_overwritten(self):
        target = self.archive / "library"
        target.mkdir()
        (target / "keep.txt").write_text("keep")
        with self.assertRaisesRegex(RuntimeError, "leaving it unchanged"):
            dependencies.bootstrap(self.archive)
        self.assertEqual((target / "keep.txt").read_text(), "keep")

    def test_dirty_dependency_is_not_overwritten(self):
        dependencies.bootstrap(self.archive)
        target = self.archive / "library"
        (target / "version.txt").write_text("local changes")
        with self.assertRaisesRegex(RuntimeError, "local changes"):
            dependencies.bootstrap(self.archive)
        self.assertEqual((target / "version.txt").read_text(), "local changes")

    def test_wrong_revision_is_not_reset(self):
        subprocess.run(["git", "clone", "--quiet", str(self.origin), str(self.archive / "library")], check=True)
        with self.assertRaisesRegex(RuntimeError, "required revision"):
            dependencies.bootstrap(self.archive)
        self.assertEqual((self.archive / "library" / "version.txt").read_text(), "newer\n")

    def test_failed_fetch_can_be_retried(self):
        self.git(self.archive, "config", "--file", str(self.archive / ".gitmodules"), "submodule.library.url", str(self.base / "missing"))
        with self.assertRaises(subprocess.CalledProcessError):
            dependencies.bootstrap(self.archive)
        self.assertFalse((self.archive / "library").exists())
        self.assertFalse(list(self.archive.glob(".library-bootstrap-*")))
        self.configure(self.archive)
        dependencies.bootstrap(self.archive)
        self.assertEqual(self.git(self.archive / "library", "rev-parse", "HEAD"), self.revision)

    def test_git_checkout_keeps_submodule_behavior(self):
        parent = self.base / "parent"
        parent.mkdir()
        self.git(parent, "init", "--quiet")
        self.git(parent, "config", "user.name", "Test Author")
        self.git(parent, "config", "user.email", "test@example.invalid")
        self.git(parent, "-c", "protocol.file.allow=always", "submodule", "add", str(self.origin), "library")
        self.git(parent / "library", "checkout", "--quiet", "--detach", self.revision)
        self.git(parent, "add", ".")
        self.git(parent, "commit", "--quiet", "-m", "Pinned submodule")
        shutil.rmtree(parent / "library")
        with patch.dict(os.environ, {"GIT_ALLOW_PROTOCOL": "file"}):
            dependencies.bootstrap(parent)
        self.assertEqual(self.git(parent / "library", "rev-parse", "HEAD"), self.revision)


class PublicationPinTests(unittest.TestCase):
    def test_archive_pins_match_gitlinks(self):
        root = Path(__file__).resolve().parents[1]
        if not dependencies.is_checkout_root(root):
            self.skipTest("Source archive has no parent Git metadata")
        for name, revision in dependencies.DEPENDENCY_REVISIONS.items():
            fields = dependencies.git(root, "ls-tree", "HEAD", name).split()
            self.assertEqual(fields[:3], ["160000", "commit", revision])


if __name__ == "__main__":
    unittest.main()
