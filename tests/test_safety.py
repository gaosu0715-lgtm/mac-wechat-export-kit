import json
import os
from pathlib import Path
import tempfile
import unittest

from fixtures import FAKE_KEYS, make_fixtures, save_keys
from mac_wechat_export_kit.cipher import load_keys, load_library
from mac_wechat_export_kit.safety import ExportError, canonical, private_json, scoped_databases


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()

    def test_exact_key_manifest(self):
        path = self.base / "keys.json"
        save_keys(path)
        self.assertEqual(load_keys(path), FAKE_KEYS)

    def test_public_key_file_refused_without_chmod(self):
        path = self.base / "keys.json"
        save_keys(path)
        path.chmod(0o644)
        with self.assertRaisesRegex(ExportError, "0600"):
            load_keys(path)
        self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_key_symlink_refused(self):
        target = self.base / "keys.json"
        save_keys(target)
        link = self.base / "link"
        link.symlink_to(target)
        with self.assertRaisesRegex(ExportError, "symlink_rejected"):
            load_keys(link)

    def test_extra_shard_key_refused(self):
        path = self.base / "keys.json"
        save_keys(path)
        data = private_json(path)
        data["keys"]["message/message_1.db"] = {"enc_key": "33" * 32}
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ExportError, "exact_two_databases"):
            load_keys(path)

    def test_passphrase_not_accepted_as_raw_key(self):
        path = self.base / "keys.json"
        save_keys(path)
        data = private_json(path)
        data["keys"]["contact/contact.db"]["enc_key"] = "synthetic-password"
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ExportError, "raw_key_requires"):
            load_keys(path)

    def test_no_shard_discovery(self):
        root = make_fixtures(self.base / "fabricated")
        self.assertEqual(set(scoped_databases(root)), {"contact/contact.db", "message/message_0.db"})

    def test_sidecar_symlink_refused(self):
        root = make_fixtures(self.base / "fabricated")
        (root / "message/message_0.db-wal").symlink_to(self.base / "absent")
        with self.assertRaisesRegex(ExportError, "sidecar_symlink_rejected"):
            scoped_databases(root)

    def test_parent_symlink_refused(self):
        root = make_fixtures(self.base / "fabricated")
        (self.base / "alias").symlink_to(root, target_is_directory=True)
        with self.assertRaisesRegex(ExportError, "symlink_rejected"):
            scoped_databases(self.base / "alias")

    def test_library_digest_refused_before_load(self):
        path = self.base / "fake.dylib"
        path.write_bytes(b"synthetic")
        with self.assertRaisesRegex(ExportError, "library_digest_mismatch"):
            load_library(path, "00" * 32)
