"""All signing, process and recovery calls are mocks over synthetic bundles."""

from pathlib import Path
import os
import plistlib
import shutil
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from test_capture_policy import original_entitlements
from mac_wechat_export_kit import mac_host
from mac_wechat_export_kit.capture_policy import GROUP, GROUP_KEY, intended_entitlements
from mac_wechat_export_kit.safety import ExportError
from mac_wechat_export_kit.session import Session


class HostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.original = self.base / "Original.app"
        (self.original / "Contents/MacOS").mkdir(parents=True)
        (self.original / "Contents/MacOS/WeChat").write_bytes(b"synthetic-main")
        (self.original / "Contents/vendor.fixture").write_bytes(b"synthetic-vendor")
        self.baseline = {"original": {"main": mac_host.digest_file(self.original / "Contents/MacOS/WeChat"),
                                     "nested": mac_host.bundle_digest(self.original), "entitlements": original_entitlements()}}
        self.session = Session.create(self.base / "private-session",
                                      {"app_path": str(self.original), "state_dir": str(self.base / "private-session")}, self.baseline)
        self.host = mac_host.MacHost()

    def test_sign_main_once_preserve_nested_and_fifteen_entitlements(self):
        actions, signed = [], []
        def checked(args, timeout=10):
            actions.append(args)
            if args[0] == "/usr/bin/ditto":
                shutil.copytree(self.original, self.session.disabled)
            if "--force" in args:
                signed.append(True)
            return "flags=0x10002(adhoc,runtime)"
        self.host.checked = checked
        self.host.snapshot = lambda app: self.baseline["original"]
        self.host.app_processes = lambda app: []
        self.host.guard = lambda app: None
        self.host.entitlements = lambda app: intended_entitlements(original_entitlements()) if signed else original_entitlements()
        self.host.prepare(self.session)
        signs = [args for args in actions if "--force" in args]
        self.assertEqual(len(signs), 1)
        self.assertNotIn("--deep", signs[0])
        self.assertEqual(signs[0][-1], str(self.session.disabled))
        self.assertIn("runtime", signs[0])
        self.assertEqual(mac_host.bundle_digest(self.original), mac_host.bundle_digest(self.session.disabled))
        with (self.session.root / "copy-entitlements.plist").open("rb") as stream:
            result = plistlib.load(stream)
        self.assertEqual(len(result), 15)
        self.assertEqual(result[GROUP_KEY], GROUP)
        self.assertTrue(result["com.apple.security.app-sandbox"])
        with self.assertRaises(FileExistsError):
            self.session.reserve("sign")

    def test_original_changed_blocks_restore_before_launch(self):
        self.host.snapshot = lambda app: {"changed": True}
        with patch.object(mac_host.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(ExportError, "original_integrity_changed"):
                self.host.restore(self.session)
        launch.assert_not_called()

    def test_running_original_blocks_preparation_without_signing(self):
        self.host.snapshot = lambda app: self.baseline["original"]
        self.host.app_processes = lambda app: [1]
        self.host.checked = Mock()
        with self.assertRaisesRegex(ExportError, "quit_original"):
            self.host.prepare(self.session)
        self.host.checked.assert_not_called()

    def test_running_copy_hands_back_without_quit_or_touching_running_original(self):
        self.session.active.mkdir()
        self.host.assert_original_unchanged = Mock()
        self.host.app_processes = lambda app: [1] if app in (self.session.active, self.original) else []
        self.host.command, self.host.checked = Mock(), Mock()
        with patch.object(mac_host.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(ExportError, "manual_copy_quit_required"):
                self.host.restore(self.session)
        launch.assert_not_called()
        self.host.command.assert_not_called()
        self.host.checked.assert_not_called()
        self.assertTrue(self.session.active.exists())
        self.assertFalse(self.session.record["cleanup_complete"])

    def test_restore_unregisters_only_copy_and_launches_exact_original(self):
        self.session.active.mkdir()
        running, commands, launches = [], [], []
        self.host.assert_original_unchanged = Mock()
        self.host.app_processes = lambda app: running[:] if app == self.original else []
        self.host.checked = lambda args, timeout: commands.append(args) or ""
        def launch(args, **kwargs):
            launches.append(args)
            running.append((123, os.geteuid(), str(self.original / "Contents/MacOS/WeChat")))
            return NS()
        with patch.object(mac_host.subprocess, "Popen", side_effect=launch):
            self.host.restore(self.session)
        self.assertEqual(launches, [[str(self.original / "Contents/MacOS/WeChat")]])
        self.assertEqual(commands[0][-2:], ["-u", str(self.session.active)])
        self.assertTrue(self.session.disabled.exists())
        self.assertFalse(self.session.active.exists())
        self.assertTrue(self.session.record["cleanup_complete"])

    def test_only_copy_helpers_remaining_still_requires_human_exit(self):
        self.session.active.mkdir()
        self.host.assert_original_unchanged = Mock()
        self.host.app_processes = lambda app: [(4321, 501, "synthetic-helper")] if app == self.session.active else []
        self.host.checked = Mock()
        with self.assertRaisesRegex(ExportError, "manual_copy_quit_required"):
            self.host.restore(self.session)
        self.host.checked.assert_not_called()

    def test_running_disabled_copy_also_blocks_original_launch(self):
        self.session.disabled.mkdir()
        self.host.assert_original_unchanged = Mock()
        self.host.app_processes = lambda app: [1] if app == self.session.disabled else []
        with patch.object(mac_host.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(ExportError, "manual_copy_quit_required"):
                self.host.restore(self.session)
        launch.assert_not_called()

    def test_existing_original_never_receives_command_or_duplicate_launch(self):
        self.host.assert_original_unchanged = Mock()
        self.host.app_processes = lambda app: [(123, os.geteuid(), str(self.original / "Contents/MacOS/WeChat"))] if app == self.original else []
        self.host.command, self.host.checked = Mock(), Mock()
        with patch.object(mac_host.subprocess, "Popen") as launch:
            self.host.restore(self.session)
        launch.assert_not_called()
        self.host.command.assert_not_called()
        self.host.checked.assert_not_called()
        self.assertTrue(self.session.record["cleanup_complete"])

    def test_original_helpers_alone_do_not_count_as_restored_or_allow_duplicate_launch(self):
        self.host.assert_original_unchanged = Mock()
        self.host.app_processes = lambda app: [(123, os.geteuid(), str(self.original / "Contents/Helpers/synthetic"))] if app == self.original else []
        with patch.object(mac_host.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(ExportError, "original_main_not_observed"):
                self.host.restore(self.session)
        launch.assert_not_called()
        self.assertFalse(self.session.record["cleanup_complete"])

    def test_original_path_inside_session_is_rejected_before_native_operations(self):
        self.session.active.mkdir()
        self.session.save(config={**self.session.record["config"], "app_path": str(self.session.active)})
        self.host.assert_original_unchanged = Mock()
        self.host.checked = Mock()
        with self.assertRaisesRegex(ExportError, "recovery_path_overlap"):
            self.host.restore(self.session)
        self.host.assert_original_unchanged.assert_not_called()
        self.host.checked.assert_not_called()

    def test_copy_reappears_during_unregister_blocks_rename_and_launch(self):
        self.session.active.mkdir()
        self.host.assert_original_unchanged = Mock()
        running = []
        self.host.app_processes = lambda app: running[:] if app == self.session.active else []
        self.host.checked = lambda args, timeout: running.append(123) or ""
        with patch.object(mac_host.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(ExportError, "manual_copy_quit_required"):
                self.host.restore(self.session)
        launch.assert_not_called()
        self.assertTrue(self.session.active.exists())

    def test_original_changes_after_copy_disabled_keeps_partial_state(self):
        self.session.active.mkdir()
        self.host.snapshot = Mock(side_effect=[self.baseline["original"], {"changed": True}])
        self.host.app_processes = lambda app: []
        self.host.checked = Mock(return_value="")
        with patch.object(mac_host.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(ExportError, "original_integrity_changed"):
                self.host.restore(self.session)
        launch.assert_not_called()
        self.assertTrue(self.session.record["copy_cleanup_complete"])
        self.assertFalse(self.session.record["original_integrity_unchanged"])
        self.assertFalse(self.session.record["cleanup_complete"])

    def test_failed_repeat_restore_does_not_keep_stale_success_flags(self):
        self.session.save(cleanup_complete=True, original_user_confirmed=True, original_integrity_unchanged=True)
        self.host.snapshot = lambda app: {"changed": True}
        with self.assertRaisesRegex(ExportError, "original_integrity_changed"):
            self.host.restore(self.session)
        self.assertFalse(self.session.record["cleanup_complete"])
        self.assertFalse(self.session.record["original_user_confirmed"])
        self.assertFalse(self.session.record["original_integrity_unchanged"])

    def test_unknown_platform_exits_before_native_commands(self):
        self.host.checked = Mock()
        with patch.object(mac_host.platform, "system", return_value="Linux"), patch.object(mac_host.os, "geteuid", return_value=501):
            with self.assertRaisesRegex(ExportError, "unsupported_platform"):
                self.host.preflight({})
        self.host.checked.assert_not_called()

    def test_lldb_path_supports_selected_xcode_sibling_framework(self):
        developer = self.base / "Xcode.app/Contents/Developer"
        module = developer.parent / "SharedFrameworks/LLDB.framework/Resources/Python"
        developer.mkdir(parents=True)
        module.mkdir(parents=True)
        self.assertEqual(mac_host.trusted_lldb_path(module, developer), module)
        with self.assertRaisesRegex(ExportError, "lldb_outside"):
            mac_host.trusted_lldb_path(self.base, developer)

    def test_entitlement_xml_and_der_tree_parsing(self):
        xml = plistlib.dumps({"synthetic": True}).decode()
        self.assertEqual(mac_host.parse_entitlements(xml), {"synthetic": True})
        tree = "[Dict]\n\t[Key] synthetic\n\t[Value]\n\t\t[Bool] true\n"
        self.assertEqual(mac_host.parse_entitlements(tree), {"synthetic": True})
        with self.assertRaises(ExportError):
            mac_host.parse_entitlements("[Number] 1")

    def test_native_version_gate_rejects_before_signing_or_debugger(self):
        info = {"CFBundleIdentifier": "com.tencent.xinWeChat", "CFBundleShortVersionString": "unsupported",
                "CFBundleVersion": "269602", "CFBundleExecutable": "WeChat"}
        with (self.original / "Contents/Info.plist").open("wb") as stream:
            plistlib.dump(info, stream)
        calls = []
        def checked(args, timeout=10):
            calls.append(args)
            return "27.0.1" if "sw_vers" in args[0] else "System Integrity Protection status: enabled."
        self.host.checked = checked
        with patch.object(mac_host.platform, "system", return_value="Darwin"), \
             patch.object(mac_host.platform, "machine", return_value="arm64"), \
             patch.object(mac_host.os, "geteuid", return_value=501):
            with self.assertRaisesRegex(ExportError, "unsupported_wechat_version"):
                self.host.preflight({"app_path": str(self.original)})
        self.assertTrue(all("codesign" not in args[0] and "lldb" not in args[0] for args in calls))
