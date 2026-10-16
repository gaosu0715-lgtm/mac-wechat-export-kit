import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fixtures import CONTACT, SELF, USERNAME, RAW_ROWS, TABLE, PlainFixtureDB, make_fixtures
from mac_wechat_export_kit.cli import main
from mac_wechat_export_kit.exporter import export_conversation, verify_output
from mac_wechat_export_kit.safety import ExportError


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = make_fixtures(self.base / "fabricated")
        self.output = self.base / "private-output"

    def export(self, **kwargs):
        options = dict(contact_name=CONTACT, expected_username=USERNAME, self_username=SELF,
                       output=self.output, page_size=2)
        options.update(kwargs)
        return export_conversation(lambda relative: PlainFixtureDB(self.root / relative), **options)

    def mutate(self, relative, sql):
        with sqlite3.connect(self.root / relative) as db:
            db.executescript(sql)

    def test_roundtrip_scope_digest_order_permissions_offline(self):
        paths = [self.root / "contact/contact.db", self.root / "message/message_0.db"]
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        summary = self.export()
        self.assertEqual(summary["message_count"], 6)
        self.assertEqual(summary["html_pages"], 3)
        self.assertFalse(summary["full_history_verified"])
        self.assertTrue(verify_output(self.output)["verified"])
        data = json.loads((self.output / "messages.json").read_text())
        self.assertEqual([r["local_id"] for r in data["messages"]], [1, 2, 3, 4, 5, 6])
        self.assertEqual(data["messages"][4]["sender"], "system")
        combined = ""
        for path in self.output.rglob("*"):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600 if path.is_file() else 0o700)
            if path.is_file():
                combined += path.read_text()
        for sentinel in ("OTHER_CHAT_SENTINEL", "UNAPPROVED_SHARD_SENTINEL", "MEDIA_TOKEN_SENTINEL", "FORWARD_PAYLOAD_SENTINEL"):
            self.assertNotIn(sentinel, combined)
        self.assertNotIn(USERNAME, combined)
        page = (self.output / "HTML/page-00001.html").read_text()
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<script>", page)
        self.assertIn("default-src 'none'", page)
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})

    def test_duplicate_display_name_refused_before_output(self):
        self.mutate("contact/contact.db", "INSERT INTO contact VALUES('duplicate'," + "CAST(x'" + CONTACT.encode().hex() + "' AS TEXT),'');")
        with self.assertRaisesRegex(ExportError, "contact_missing_ambiguous"):
            self.export()
        self.assertFalse(self.output.exists())

    def test_wrong_binding_refused(self):
        with self.assertRaisesRegex(ExportError, "binding_changed"):
            self.export(expected_username="wrong_fixture")

    def test_group_rejected(self):
        with self.assertRaisesRegex(ExportError, "invalid_one_to_one"):
            self.export(expected_username="group@chatroom")

    def test_third_participant_refused(self):
        self.mutate("message/message_0.db", "INSERT INTO Name2Id(rowid,user_name) VALUES(99,'stranger_fixture');")
        with self.assertRaisesRegex(ExportError, "unexpected_conversation_participant"):
            self.export()
        self.assertFalse((self.output / "manifest.json").exists())

    def test_unknown_non_system_sender_refused(self):
        self.mutate("message/message_0.db", 'UPDATE "' + TABLE + '" SET real_sender_id=99 WHERE local_id=1;')
        with self.assertRaisesRegex(ExportError, "non_system_sender_unresolved"):
            self.export()
        self.assertFalse((self.output / "manifest.json").exists())

    def test_duplicate_local_id_refused(self):
        self.mutate("message/message_0.db", 'UPDATE "' + TABLE + '" SET local_id=1 WHERE local_id=2;')
        with self.assertRaisesRegex(ExportError, "duplicate_local_id"):
            self.export()

    def test_empty_chat_supported(self):
        self.mutate("message/message_0.db", 'DELETE FROM "' + TABLE + '";')
        self.assertEqual(self.export()["message_count"], 0)
        self.assertTrue(verify_output(self.output)["verified"])

    def test_existing_output_not_overwritten(self):
        self.output.mkdir()
        with self.assertRaises(FileExistsError):
            self.export()

    def test_bad_page_size(self):
        with self.assertRaisesRegex(ExportError, "invalid_page_size"):
            self.export(page_size=0)

    def test_tampered_output_rejected(self):
        self.export()
        (self.output / "messages.txt").write_text("tampered")
        with self.assertRaisesRegex(ExportError, "output_digest_mismatch"):
            verify_output(self.output)

    def test_manifest_traversal_refused(self):
        self.export()
        path = self.output / "manifest.json"
        value = json.loads(path.read_text())
        value["sha256"]["../../outside"] = "00" * 32
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ExportError, "manifest_file_scope_mismatch"):
            verify_output(self.output)

    def test_config_errors_do_not_echo_input(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            result = main(["export", "--config", str(self.base / "PRIVATE_PATH_SENTINEL"), "--output", str(self.output)])
        self.assertEqual(result, 2)
        self.assertNotIn("PRIVATE_PATH_SENTINEL", stream.getvalue())

    def test_arbitrary_exception_not_echoed(self):
        stream = io.StringIO()
        with patch("mac_wechat_export_kit.cli.run_export", side_effect=RuntimeError("KEY_AND_BODY_SENTINEL")):
            with contextlib.redirect_stdout(stream):
                self.assertEqual(main(["export", "--config", "unused", "--output", "unused"]), 2)
        self.assertNotIn("KEY_AND_BODY_SENTINEL", stream.getvalue())

    def test_sql_like_name_is_only_data(self):
        with self.assertRaisesRegex(ExportError, "contact_missing"):
            self.export(contact_name="' OR 1=1; --")

    def test_argument_errors_do_not_echo_values(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as result:
                main(["export", "--config", "unused", "--output", "unused", "--key", "SECRET_ARGUMENT_SENTINEL"])
        self.assertEqual(result.exception.code, 2)
        self.assertNotIn("SECRET_ARGUMENT_SENTINEL", stdout.getvalue() + stderr.getvalue())

    def test_alternate_body_column_used(self):
        self.mutate("message/message_0.db", 'UPDATE "' + TABLE
                    + '" SET compress_content=message_content,message_content=NULL WHERE local_id=1;')
        self.export()
        data = json.loads((self.output / "messages.json").read_text())
        self.assertEqual(data["messages"][0]["text"], "合成🙂\nfirst")

    def test_missing_completion_marker_not_verified(self):
        self.output.mkdir()
        with self.assertRaises(FileNotFoundError):
            verify_output(self.output)
