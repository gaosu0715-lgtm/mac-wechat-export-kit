"""Pure synthetic GUI snapshots; never instantiate a macOS backend."""

import json
from types import SimpleNamespace as NS
import unittest

from mac_wechat_export_kit.permission_windows import PermissionObserver, button_features, evaluate


class PermissionTests(unittest.TestCase):
    def snapshot(self, window):
        return {"session_verified": True, "inventory_ok": True, "screen_query_ok": True,
                "agents": [{"agent": "SecurityAgent", "pid": 123, "identity_verified": True,
                            "visible_count": 1, "windows": [window]}]}

    def test_verified_allow_deny_window_stops(self):
        window = {"visible": True, "owner_verified": True, "current_session": True, "window_id": 7,
                  "features": button_features(["Allow", "Deny"])}
        snapshot = self.snapshot(window)
        self.assertEqual(evaluate(snapshot)["status"], "verified_permission_request")
        observer = PermissionObserver(NS(snapshot=lambda: snapshot))
        with self.assertRaisesRegex(RuntimeError, "system_permission_window_present"):
            observer.check()

    def test_visible_agent_count_alone_is_unknown(self):
        snapshot = self.snapshot({"visible": True, "owner_verified": True, "current_session": True,
                                  "window_id": 7, "features": button_features(["OK"])})
        self.assertEqual(evaluate(snapshot)["status"], "unknown")
        with self.assertRaisesRegex(RuntimeError, "permission_window_unverified"):
            PermissionObserver(NS(snapshot=lambda: snapshot)).check()

    def test_unknown_gui_session_never_claims_no_prompt(self):
        self.assertEqual(evaluate({"session_verified": False})["status"], "unknown")

    def test_hidden_agent_window_does_not_mean_permission_prompt(self):
        snapshot = self.snapshot({"visible": False})
        snapshot["agents"][0]["visible_count"] = 0
        self.assertEqual(PermissionObserver(NS(snapshot=lambda: snapshot)).check()["status"], "no_verified_permission_window")

    def test_backend_error_is_redacted(self):
        def failed():
            raise OSError("PRIVATE_METADATA_SENTINEL")
        observer = PermissionObserver(NS(snapshot=failed))
        with self.assertRaisesRegex(RuntimeError, "permission_window_unverified"):
            observer.check()
        self.assertNotIn("PRIVATE_METADATA_SENTINEL", json.dumps(observer.last_observation))
