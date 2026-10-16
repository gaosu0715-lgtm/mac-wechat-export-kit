"""Release privacy regression in an isolated, fabricated Git repository."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("release_check", Path(__file__).resolve().parents[1] / "scripts/release_check.py")
release_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_check)


class ReleaseTests(unittest.TestCase):
    def test_staged_ignored_database_and_literal_key_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            for name in release_check.ROOT_FILES:
                (root / name).write_text("synthetic\n")
            (root / ".gitignore").write_text("*.db\nprivate*\n")
            (root / "docs/licenses").mkdir(parents=True)
            (root / "docs/licenses/upstream-MIT.md").write_text("synthetic\n")
            (root / "examples").mkdir()
            (root / "examples/config.example.json").write_text('{"timezone":"UTC"}')
            (root / "examples/setup.example.json").write_text('{"timezone":"UTC"}')
            (root / "docs/unsafe.md").write_text(json.dumps({"enc_key": "ab" * 32}))
            (root / "toy.db").write_bytes(b"synthetic")
            subprocess.run(["git", "-C", str(root), "add", "-f", "toy.db"], check=True)
            (root / "docs/private-report.md").write_text("synthetic private report")
            subprocess.run(["git", "-C", str(root), "add", "-f", "docs/private-report.md"], check=True)
            captured = io.StringIO()
            with patch.object(release_check, "ROOT", root), contextlib.redirect_stdout(captured):
                self.assertEqual(release_check.main(), 2)
            failures = json.loads(captured.getvalue())["failures"]
            self.assertIn({"file": "toy.db", "code": "unexpected_candidate_type"}, failures)
            self.assertIn({"file": "docs/unsafe.md", "code": "literal_raw_key"}, failures)
            self.assertIn({"file": "docs/private-report.md", "code": "ignored_candidate"}, failures)
            self.assertIn({"file": "toy.db", "code": "ignored_candidate"}, failures)
            self.assertNotIn("ab" * 32, captured.getvalue())
