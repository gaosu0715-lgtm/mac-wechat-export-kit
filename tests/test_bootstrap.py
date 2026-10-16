import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from fixtures import CONTACT, SELF, USERNAME
from runtime_fakes import FakeRuntime
from test_capture_policy import synthetic_page
from mac_wechat_export_kit import bootstrap
from mac_wechat_export_kit.cli import main
from mac_wechat_export_kit.runtime_capture import CaptureResult
from mac_wechat_export_kit.safety import DATABASES, ExportError, private_text
from mac_wechat_export_kit.session import Session


class FakeHost:
    def __init__(self, fail=None):
        self.actions, self.fail, self.original_running = [], fail, True

    def preflight(self, config):
        self.actions.append("preflight")
        if self.fail == "unsupported":
            raise ExportError("unsupported_wechat_version")
        return {"original": {"fixture": True}, "supported": {"synthetic": True}, "lldb_python": "synthetic"}

    def app_processes(self, app):
        return [123] if self.original_running else []

    def prepare(self, session):
        self.actions.append("prepare")
        session.reserve("sign")
        session.save(signings=1)
        session.disabled.mkdir()
        if self.fail == "prepare":
            raise ExportError("candidate_entitlements_or_nested_changed")

    def restore(self, session):
        self.actions.append("restore")
        if self.fail == "restore":
            raise ExportError("manual_copy_quit_required")
        self.original_running = True
        session.save(cleanup_complete=True, copy_cleanup_complete=True, original_integrity_unchanged=True, stage="restored")


class FakeUI:
    def __init__(self, host, cancel=None):
        self.host, self.cancel, self.actions = host, cancel, []
    def announce(self, stage): self.actions.append(stage)
    def show_plan(self, config): self.actions.append("show_plan")
    def show_recovery(self, config): self.actions.append("show_recovery")
    def show_copy_exit(self, session): self.actions.append("show_copy_exit")
    def confirm_binding(self, config, binding):
        self.actions.append("binding")
        if self.cancel == "binding":
            raise ExportError("cancelled")
    def confirm(self, stage):
        self.actions.append(stage)
        if stage == self.cancel:
            raise ExportError("cancelled")
        if stage == "quit_original":
            self.host.original_running = False


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "fabricated"
        (self.root / "contact").mkdir(parents=True)
        (self.root / "message").mkdir()
        self.keys = {name: bytes([75 + i]) * 32 for i, name in enumerate(DATABASES)}
        for name in DATABASES:
            (self.root / name).write_bytes(synthetic_page(self.keys[name]))
        self.config = {"app_path": str(self.base / "Original.app"), "db_root": str(self.root),
                       "state_dir": str(self.base / "private-session"), "sqlcipher_library": str(self.base / "synthetic.dylib"),
                       "library_sha256": "00" * 32, "contact_name": CONTACT, "expected_username": USERNAME,
                       "self_username": SELF, "timezone": "UTC"}
        self.host = FakeHost()
        self.ui = FakeUI(self.host)
        self.export = Mock(return_value={"message_count": 0})

    def capture(self, host, session, pages, ui):
        host.actions.append("capture")
        session.reserve("launch")
        session.save(launches=1)
        return CaptureResult(self.keys, {"synthetic": True})

    def validate(self, session, keys, pages):
        self.host.actions.append("validate")
        with private_text(session.root / "keys.json") as stream:
            json.dump({"synthetic": True}, stream)
        session.save(keys_verified=True, capture_complete=True)

    def run_guide(self, **kwargs):
        options = {"capture_runner": self.capture, "key_validator": self.validate, "export_runner": self.export,
                   "binding_resolver": lambda config, keys: {"expected_username": USERNAME, "self_username": SELF}}
        options.update(kwargs)
        return bootstrap.guide(self.config, self.host, self.ui, **options)

    def test_plan_has_no_mutations_or_page_reads(self):
        with patch.object(bootstrap, "read_selected_pages", side_effect=AssertionError("must not read")):
            result = bootstrap.plan(self.config, self.host)
        self.assertFalse(result["live_actions_executed"])
        self.assertFalse(result["application_quit_requests"])
        self.assertTrue(result["user_menu_exit_required"])
        self.assertEqual(self.host.actions, ["preflight"])
        self.assertFalse(Path(self.config["state_dir"]).exists())

    def test_complete_simulated_order_and_separate_success_fields(self):
        result = self.run_guide()
        self.assertTrue(result["workflow_complete"])
        self.assertEqual(self.host.actions, ["preflight", "prepare", "capture", "validate", "restore"])
        self.assertLess(self.ui.actions.index("consent"), self.ui.actions.index("preparing"))
        self.assertLess(self.ui.actions.index("restored"), self.ui.actions.index("exporting"))
        self.assertLess(self.ui.actions.index("binding"), self.ui.actions.index("exporting"))
        session = Session.load(self.config["state_dir"])
        self.assertTrue(session.record["keys_verified"])
        self.assertTrue(session.record["cleanup_complete"])
        self.assertTrue(session.record["original_user_confirmed"])
        self.assertEqual(session.record["launches"], 1)

    def test_decline_consent_has_no_state_or_page_reads(self):
        self.ui.cancel = "consent"
        with patch.object(bootstrap, "read_selected_pages", side_effect=AssertionError("must not read")):
            with self.assertRaisesRegex(ExportError, "cancelled"):
                self.run_guide()
        self.assertEqual(self.host.actions, ["preflight"])
        self.assertFalse(Path(self.config["state_dir"]).exists())

    def test_unsupported_version_exits_before_consent_or_state(self):
        self.host.fail = "unsupported"
        with self.assertRaisesRegex(ExportError, "unsupported"):
            self.run_guide()
        self.assertNotIn("consent", self.ui.actions)
        self.assertFalse(Path(self.config["state_dir"]).exists())

    def test_preparation_failure_restores_without_capture(self):
        self.host.fail = "prepare"
        with self.assertRaises(ExportError):
            self.run_guide()
        self.assertNotIn("capture", self.host.actions)
        self.assertIn("restore", self.host.actions)
        self.export.assert_not_called()

    def test_capture_deadline_restores_and_does_not_retry(self):
        def fail_capture(host, session, pages, ui):
            session.reserve("launch")
            raise ExportError("capture_deadline")
        with self.assertRaisesRegex(ExportError, "capture_deadline"):
            self.run_guide(capture_runner=fail_capture)
        self.assertIn("restore", self.host.actions)
        self.export.assert_not_called()
        session = Session.load(self.config["state_dir"])
        with self.assertRaises(FileExistsError):
            session.reserve("launch")

    def test_cleanup_failure_blocks_export_even_after_keys_verified(self):
        self.host.fail = "restore"
        with self.assertRaisesRegex(ExportError, "manual_copy_quit_required"):
            self.run_guide()
        session = Session.load(self.config["state_dir"])
        self.assertTrue(session.record["keys_verified"])
        self.assertFalse(session.record["cleanup_complete"])
        self.assertIn("manual_copy_exit", self.ui.actions)
        self.assertIn("manual_recovery", self.ui.actions)
        self.assertEqual(session.record["recovery_error_code"], "manual_copy_quit_required")
        self.export.assert_not_called()

    def test_human_copy_exit_continues_only_recovery_then_bootstrap_completion(self):
        self.host.fail = "restore"
        previous_confirm = self.ui.confirm
        def confirm(stage):
            previous_confirm(stage)
            if stage == "quit_copy":
                self.host.fail = None
        self.ui.confirm = confirm
        result = self.run_guide(bootstrap_only=True)
        self.assertTrue(result["bootstrap_complete"])
        self.assertEqual(self.host.actions.count("capture"), 1)
        self.assertEqual(self.host.actions.count("prepare"), 1)
        self.assertEqual(self.host.actions.count("restore"), 2)
        self.assertTrue(Session.load(self.config["state_dir"]).record["manual_copy_exit_required"])
        self.export.assert_not_called()

    def test_cancel_copy_exit_preserves_keys_but_blocks_confirmation_export(self):
        self.host.fail, self.ui.cancel = "restore", "quit_copy"
        with self.assertRaisesRegex(ExportError, "cancelled"):
            self.run_guide()
        session = Session.load(self.config["state_dir"])
        self.assertTrue(session.record["keys_verified"])
        self.assertFalse(session.record["cleanup_complete"])
        self.assertFalse(session.record["original_user_confirmed"])
        self.assertEqual(self.host.actions.count("restore"), 1)
        self.assertNotIn("restored", self.ui.actions)
        self.export.assert_not_called()

    def test_capture_and_recovery_errors_survive_later_recovery_independently(self):
        self.host.fail = "restore"
        def fail_capture(*args): raise ExportError("capture_deadline")
        with self.assertRaisesRegex(ExportError, "manual_copy_quit_required"):
            self.run_guide(capture_runner=fail_capture)
        session = Session.load(self.config["state_dir"])
        self.assertEqual(session.record["workflow_error_code"], "capture_deadline")
        self.assertEqual(session.record["recovery_error_code"], "manual_copy_quit_required")
        self.host.fail = None
        bootstrap.recover(self.config["state_dir"], self.host, self.ui)
        session = Session.load(self.config["state_dir"])
        self.assertTrue(session.record["cleanup_complete"])
        self.assertTrue(session.record["original_user_confirmed"])
        self.assertFalse(session.record["keys_verified"])
        self.assertFalse(session.record["capture_complete"])
        self.assertEqual(session.record["workflow_error_code"], "capture_deadline")
        self.assertIsNone(session.record["recovery_error_code"])
        self.assertIn({"phase": "recovery", "code": "manual_copy_quit_required"}, session.record["error_history"])

    def test_capture_failure_still_requests_original_confirmation(self):
        def fail_capture(*args): raise ExportError("capture_deadline")
        with self.assertRaisesRegex(ExportError, "capture_deadline"):
            self.run_guide(capture_runner=fail_capture)
        session = Session.load(self.config["state_dir"])
        self.assertTrue(session.record["cleanup_complete"])
        self.assertTrue(session.record["original_user_confirmed"])
        self.assertFalse(session.record["capture_complete"])
        self.export.assert_not_called()

    def test_live_debugger_supervision_blocks_host_restore_until_verified_exit(self):
        simulation = FakeRuntime(detach_ok=False)
        held = bootstrap.ManualDetachRequired(simulation.api, NS(), simulation.target, simulation.process)
        def capture_held(*args): raise held
        prompts = []
        def manual_exit():
            self.assertNotIn("restore", self.host.actions)
            self.assertNotIn(("destroy",), simulation.actions)
            prompts.append(True)
            if len(prompts) == 1:
                raise KeyboardInterrupt
            simulation.state = simulation.api.eStateExited
        self.ui.manual_exit_required = manual_exit
        with patch("mac_wechat_export_kit.runtime_capture.time.sleep"):
            with self.assertRaisesRegex(ExportError, "manual_debugger_cleanup_required"):
                self.run_guide(capture_runner=capture_held)
        session = Session.load(self.config["state_dir"])
        self.assertTrue(session.record["cleanup_complete"])
        self.assertTrue(session.record["original_user_confirmed"])
        self.assertFalse(session.record["keys_verified"])
        self.assertEqual(len(prompts), 2)
        self.assertEqual(simulation.actions, [("destroy",)])
        self.assertFalse(simulation.reads)
        self.export.assert_not_called()

    def test_user_must_confirm_original_before_export(self):
        self.ui.cancel = "restored"
        with self.assertRaisesRegex(ExportError, "cancelled"):
            self.run_guide()
        self.export.assert_not_called()
        self.assertFalse(Session.load(self.config["state_dir"]).record["original_user_confirmed"])

    def test_recovery_never_reads_pages_or_keys_or_recaptures(self):
        self.host.fail = "restore"
        with self.assertRaises(ExportError): self.run_guide()
        self.host.fail = None
        (Path(self.config["state_dir"]) / "keys.json").unlink()
        with patch.object(bootstrap, "read_selected_pages", side_effect=AssertionError("must not read")), \
             patch.object(bootstrap, "native_capture", side_effect=AssertionError("must not capture")):
            result = bootstrap.recover(self.config["state_dir"], self.host, self.ui)
        self.assertFalse(result["capture_started"])
        self.assertFalse(result["export_started"])
        self.assertEqual(self.host.actions.count("prepare"), 1)

    def test_recover_confirmation_cancel_keeps_cleanup_true_confirmation_false(self):
        self.run_guide(bootstrap_only=True)
        self.ui.cancel = "restored"
        with self.assertRaisesRegex(ExportError, "cancelled"):
            bootstrap.recover(self.config["state_dir"], self.host, self.ui)
        session = Session.load(self.config["state_dir"])
        self.assertTrue(session.record["cleanup_complete"])
        self.assertFalse(session.record["original_user_confirmed"])
        self.assertEqual(session.record["stage"], "awaiting_original_confirmation")
        self.assertEqual(session.record["confirmation_error_code"], "cancelled")

    def test_recover_exception_sanitized_and_clears_previous_success(self):
        self.run_guide(bootstrap_only=True)
        self.host.restore = Mock(side_effect=RuntimeError("private synthetic diagnostic"))
        with self.assertRaisesRegex(ExportError, "restoration_failed"):
            bootstrap.recover(self.config["state_dir"], self.host, self.ui)
        session = Session.load(self.config["state_dir"])
        self.assertFalse(session.record["cleanup_complete"])
        self.assertFalse(session.record["original_user_confirmed"])
        self.assertIsNone(session.record["original_integrity_unchanged"])
        self.assertEqual(session.record["stage"], "manual_recovery")
        self.assertNotIn("private synthetic diagnostic", (session.root / "session.json").read_text())
        self.assertIn("manual_recovery", self.ui.actions)

    def test_recover_keyboard_interrupt_records_manual_handoff(self):
        self.run_guide(bootstrap_only=True)
        self.host.restore = Mock(side_effect=KeyboardInterrupt)
        with self.assertRaisesRegex(ExportError, "cancelled"):
            bootstrap.recover(self.config["state_dir"], self.host, self.ui)
        session = Session.load(self.config["state_dir"])
        self.assertFalse(session.record["cleanup_complete"])
        self.assertFalse(session.record["original_user_confirmed"])
        self.assertEqual(session.record["recovery_error_code"], "cancelled")

    def test_original_confirmation_interrupt_or_exception_never_keeps_old_confirmation(self):
        self.run_guide(bootstrap_only=True)
        for error, code in ((KeyboardInterrupt(), "cancelled"), (RuntimeError("synthetic private detail"), "original_confirmation_failed")):
            with self.subTest(code=code):
                def confirm(stage):
                    if stage == "restored": raise error
                self.ui.confirm = confirm
                with self.assertRaisesRegex(ExportError, code):
                    bootstrap.recover(self.config["state_dir"], self.host, self.ui)
                session = Session.load(self.config["state_dir"])
                self.assertTrue(session.record["cleanup_complete"])
                self.assertFalse(session.record["original_user_confirmed"])
                self.assertEqual(session.record["confirmation_error_code"], code)
                self.assertNotIn("synthetic private detail", (session.root / "session.json").read_text())

    def test_recover_old_journal_preserves_previous_error_without_keys(self):
        session = Session.create(self.config["state_dir"], self.config, {"synthetic": True})
        session.save(error_code="manual_copy_quit_required")
        session.record.pop("error_history")
        session.record.pop("workflow_error_code")
        session.save()
        bootstrap.recover(self.config["state_dir"], self.host, self.ui)
        loaded = Session.load(self.config["state_dir"])
        self.assertIn({"phase": "previous_run", "code": "manual_copy_quit_required"}, loaded.record["error_history"])
        self.assertIsNone(loaded.record["recovery_error_code"])
        self.assertFalse(loaded.record["capture_complete"])

    def test_cancel_marker_checked_without_reading_content(self):
        session = Session.create(self.config["state_dir"], self.config, {"synthetic": True})
        (session.root / "cancel.request").touch()
        with self.assertRaisesRegex(ExportError, "cancelled"):
            session.check_cancelled()

    def test_noninteractive_guide_refused_before_host_creation(self):
        stream = io.StringIO()
        with patch("sys.stdin.isatty", return_value=False), patch("mac_wechat_export_kit.mac_host.MacHost") as host:
            with contextlib.redirect_stdout(stream):
                self.assertEqual(main(["guide", "--config", "unused"]), 2)
        host.assert_not_called()
        self.assertIn("interactive_local_terminal_required", stream.getvalue())

    def test_missing_compression_dependency_stops_before_consent(self):
        self.host.preflight = lambda config: {"supported": {}, "zstandard_available": False}
        self.assertFalse(bootstrap.plan(self.config, self.host)["ready_for_live_guide"])
        with self.assertRaisesRegex(ExportError, "zstandard_required_for_guide"):
            self.run_guide()
        self.assertNotIn("consent", self.ui.actions)
        self.assertFalse(Path(self.config["state_dir"]).exists())

    def test_page_change_invalidates_keys_before_library_or_write(self):
        session = Session.create(self.config["state_dir"], self.config, {"synthetic": True})
        before = bootstrap.read_selected_pages(self.root)
        changed = bytearray((self.root / DATABASES[0]).read_bytes())
        changed[100] ^= 1
        (self.root / DATABASES[0]).write_bytes(changed)
        loader = Mock()
        with self.assertRaisesRegex(ExportError, "selected_database_pages_changed"):
            bootstrap.validate_and_save_keys(session, self.keys, before, library_loader=loader)
        loader.assert_not_called()
        self.assertFalse((session.root / "keys.json").exists())

    def test_user_cancels_quit_step_still_restores_without_capture(self):
        self.ui.cancel = "quit_original"
        with self.assertRaisesRegex(ExportError, "cancelled"):
            self.run_guide()
        self.assertEqual(self.host.actions, ["preflight", "restore"])
        self.export.assert_not_called()

    def test_cancel_contact_confirmation_stops_export_after_safe_restore(self):
        self.ui.cancel = "binding"
        with self.assertRaisesRegex(ExportError, "cancelled"):
            self.run_guide()
        self.assertTrue(Session.load(self.config["state_dir"]).record["cleanup_complete"])
        self.export.assert_not_called()

    def test_setup_accepts_blank_ids_for_post_capture_resolution(self):
        config = dict(self.config, self_username="", expected_username="")
        path = self.base / "setup.json"
        with private_text(path) as stream:
            json.dump(config, stream)
        self.assertEqual(bootstrap.load_setup(path)["expected_username"], "")

    def test_bootstrap_only_stops_before_contact_resolution_and_export(self):
        resolver = Mock(side_effect=AssertionError("must not resolve"))
        result = self.run_guide(bootstrap_only=True, binding_resolver=resolver)
        self.assertTrue(result["bootstrap_complete"])
        self.assertFalse(result["export_started"])
        resolver.assert_not_called()
        self.export.assert_not_called()
        self.assertNotIn("binding", self.ui.actions)

    def test_bootstrap_only_without_zstandard_reaches_capture_restore_not_export(self):
        previous_preflight = self.host.preflight
        def preflight(config):
            return {**previous_preflight(config), "zstandard_available": False}
        self.host.preflight = preflight
        resolver = Mock(side_effect=AssertionError("must not resolve"))
        result = self.run_guide(bootstrap_only=True, binding_resolver=resolver)
        self.assertTrue(result["bootstrap_complete"])
        self.assertIn("capture", self.host.actions)
        self.assertIn("restore", self.host.actions)
        self.assertNotIn("binding", self.ui.actions)
        resolver.assert_not_called()
        self.export.assert_not_called()

    def test_bootstrap_plan_does_not_hide_full_export_dependency(self):
        self.host.preflight = lambda config: {"supported": {}, "zstandard_available": False}
        with patch.object(bootstrap, "read_selected_pages", side_effect=AssertionError("must not read")):
            result = bootstrap.plan(self.config, self.host, bootstrap_only=True)
        self.assertTrue(result["ready_for_live_guide"])
        self.assertEqual(result["missing_dependencies"], [])
        self.assertFalse(result["ready_for_full_export"])
        self.assertEqual(result["full_export_missing_dependencies"], ["zstandard"])
        self.assertFalse(result["export_requested"])
        self.assertNotIn("read_only_export", result["stages"])
        self.assertNotIn("confirm_unique_contact_binding", result["stages"])
        self.assertIn("read_only_export", bootstrap.plan(self.config, self.host)["stages"])
        self.assertFalse(result["live_actions_executed"])
        self.assertFalse(Path(self.config["state_dir"]).exists())
