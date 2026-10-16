"""Optional integration tests: only new encrypted databases and fabricated keys."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from fixtures import CONTACT, SELF, USERNAME, FAKE_KEYS, make_fixtures, save_keys
from mac_wechat_export_kit.cipher import CipherDB, load_library
from mac_wechat_export_kit.cli import main
from mac_wechat_export_kit.safety import ExportError, private_text

LIBRARY = os.environ.get("KIT_TEST_SQLCIPHER")
DIGEST = os.environ.get("KIT_TEST_SQLCIPHER_SHA256")


@unittest.skipUnless(LIBRARY and DIGEST, "set reviewed SQLCipher library path and digest to enable encrypted fixtures")
class CipherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = load_library(LIBRARY, DIGEST)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()

    def test_encrypted_cli_end_to_end(self):
        root = self.base / "fabricated"
        def writer(relative):
            return CipherDB(self.lib, root / relative, FAKE_KEYS[relative], fixture_write=True)
        make_fixtures(root, writer)
        key_path = self.base / "keys.json"
        save_keys(key_path)
        config = {"db_root": str(root), "key_file": str(key_path), "sqlcipher_library": LIBRARY,
                  "library_sha256": DIGEST, "contact_name": CONTACT, "expected_username": USERNAME,
                  "self_username": SELF, "timezone": "UTC"}
        config_path, output = self.base / "config.json", self.base / "private-output"
        with private_text(config_path) as stream:
            json.dump(config, stream)
        paths = [root / relative for relative in FAKE_KEYS]
        for path in paths:
            self.assertNotEqual(path.read_bytes()[:16], b"SQLite format 3\x00")
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["export", "--config", str(config_path), "--output", str(output)]), 0)
            self.assertEqual(main(["verify", "--output", str(output)]), 0)
        self.assertEqual(json.loads(stdout.getvalue().splitlines()[0])["message_count"], 6)
        for value in list(FAKE_KEYS.values()) + [CONTACT, USERNAME, str(root), "synthetic notice"]:
            self.assertNotIn(value, stdout.getvalue())
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})

    def test_wrong_raw_key_and_readonly_writes_rejected(self):
        path = self.base / "toy.db"
        with CipherDB(self.lib, path, "11" * 32, fixture_write=True) as db:
            db.query("CREATE TABLE toy(id INTEGER PRIMARY KEY)")
        with self.assertRaises(ExportError):
            with CipherDB(self.lib, path, "22" * 32):
                pass
        with CipherDB(self.lib, path, "11" * 32) as db:
            with self.assertRaises(ExportError):
                db.query("INSERT INTO toy VALUES(1)")

    def test_wal_snapshot_and_no_checkpoint(self):
        path = self.base / "toy.db"
        with CipherDB(self.lib, path, "11" * 32, fixture_write=True) as writer:
            writer.query("PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0; CREATE TABLE toy(id INTEGER);")
            writer.query("INSERT INTO toy VALUES(1); PRAGMA wal_checkpoint(TRUNCATE);")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            writer.query("INSERT INTO toy VALUES(2)")
            with CipherDB(self.lib, path, "11" * 32) as reader:
                reader.query("BEGIN")
                self.assertEqual(reader.query("SELECT count(*) AS n FROM toy")[0]["n"], "2")
                writer.query("INSERT INTO toy VALUES(3)")
                self.assertEqual(reader.query("SELECT count(*) AS n FROM toy")[0]["n"], "2")
                reader.query("ROLLBACK")
                self.assertEqual(reader.query("SELECT count(*) AS n FROM toy")[0]["n"], "3")
                writer.query("BEGIN; INSERT INTO toy VALUES(4)")
                self.assertEqual(reader.query("SELECT count(*) AS n FROM toy")[0]["n"], "3")
                writer.query("ROLLBACK")
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_simulated_bootstrap_to_real_synthetic_cipher_export(self):
        from test_bootstrap import FakeHost, FakeUI
        from mac_wechat_export_kit.bootstrap import guide
        from mac_wechat_export_kit.runtime_capture import CaptureResult
        root = self.base / "self_fixture_hash/db_storage"
        make_fixtures(root, lambda name: CipherDB(self.lib, root / name, FAKE_KEYS[name], fixture_write=True))
        config = {"app_path": str(self.base / "Original.app"), "db_root": str(root),
                  "state_dir": str(self.base / "private-session"), "sqlcipher_library": LIBRARY,
                  "library_sha256": DIGEST, "contact_name": CONTACT, "expected_username": "",
                  "self_username": "", "timezone": "UTC"}
        host, stdout = FakeHost(), io.StringIO()
        def capture_runner(host, session, pages, ui):
            session.reserve("launch")
            session.save(launches=1)
            return CaptureResult({name: bytes.fromhex(key) for name, key in FAKE_KEYS.items()}, {"synthetic": True})
        with contextlib.redirect_stdout(stdout):
            result = guide(config, host, FakeUI(host), capture_runner=capture_runner)
        self.assertTrue(result["workflow_complete"])
        self.assertEqual(result["message_count"], 6)
        session = self.base / "private-session"
        self.assertEqual((session / "keys.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(session.stat().st_mode & 0o777, 0o700)
        for key in FAKE_KEYS.values():
            self.assertNotIn(key, stdout.getvalue())
        self.assertTrue((session / "export/manifest.json").is_file())
