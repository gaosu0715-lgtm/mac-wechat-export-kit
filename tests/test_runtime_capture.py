from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from runtime_fakes import FakeRuntime
from mac_wechat_export_kit import runtime_capture as runtime
from mac_wechat_export_kit.safety import ExportError


class RuntimeTests(unittest.TestCase):
    def run_capture(self, simulation, **kwargs):
        options = dict(check_external=lambda: None, verify_owned=lambda *args: None,
                       announce=simulation.announcements.append,
                       reserve_launch=lambda: simulation.actions.append(("reserve_launch",)), budget=simulation.budget)
        options.update(kwargs)
        with patch.object(runtime, "breakpoint_identity", side_effect=simulation.identity):
            return runtime.capture(simulation.api, Path("/synthetic/WeChat"), simulation.pages, {}, **options)

    def test_delayed_resolution_single_launch_and_raw_keys(self):
        sim = FakeRuntime()
        result = self.run_capture(sim)
        self.assertEqual(result.keys, sim.keys)
        self.assertEqual(result.report["memory_reads"], 4)
        self.assertEqual(sim.announcements, ["ready_for_user_login"])
        self.assertEqual(sim.actions.count(("launch",)), 1)
        self.assertEqual(sim.actions.count(("start_budget",)), 1)
        self.assertLess(sim.actions.index(("start_budget",)), sim.actions.index(("launch",)))
        self.assertTrue(all(t >= 3 for t, _, _ in sim.reads))
        self.assertIn(("detach",), sim.actions)
        self.assertIn(("destroy",), sim.actions)
        self.assertNotIn("K" * 32, repr(result))

    def test_pending_metadata_waits_without_resuming_or_reading(self):
        sim = FakeRuntime(reasons=(0, 1), resolves_at=0, events=[(120, 5, 1, (0, 1))])
        with self.assertRaisesRegex(ExportError, "capture_deadline"):
            self.run_capture(sim)
        self.assertFalse(sim.reads)
        self.assertFalse(any(action[0] == "continue" for action in sim.actions))
        self.assertFalse(sim.announcements)

    def test_never_resolved_has_original_deadline(self):
        sim = FakeRuntime(resolves_at=121, events=[])
        with self.assertRaisesRegex(ExportError, "capture_deadline"):
            self.run_capture(sim)
        self.assertEqual(sim.now, 120)
        self.assertEqual(sim.actions.count(("continue", 1)), 1)
        self.assertFalse(sim.reads)
        self.assertFalse(sim.announcements)

    def test_late_resolution_at_deadline_does_not_read(self):
        sim = FakeRuntime(resolves_at=120, events=[(120, 5, 2, (3,))])
        with self.assertRaisesRegex(ExportError, "capture_deadline"):
            self.run_capture(sim)
        self.assertFalse(sim.reads)
        self.assertFalse(sim.announcements)

    def test_signals_exceptions_and_mixed_exec_not_resumed(self):
        for reasons in ((5,), (6,), (7, 3), (7, 5)):
            with self.subTest(reasons=reasons):
                sim = FakeRuntime(reasons=reasons, resolves_at=0)
                with self.assertRaisesRegex(ExportError, "unexpected_stop"):
                    self.run_capture(sim)
                self.assertFalse(sim.reads)
                self.assertFalse(any(action[0] == "continue" for action in sim.actions))

    def test_foreign_or_malformed_breakpoint_not_resumed(self):
        for data in ([8, 1], [7], [7, 1, 8, 2], []):
            with self.subTest(data=data):
                sim = FakeRuntime(reasons=(3,), resolves_at=0)
                sim.data = data
                with self.assertRaisesRegex(ExportError, "unowned_breakpoint"):
                    self.run_capture(sim)
                self.assertFalse(sim.reads)

    def test_second_exec_and_duplicate_stop_not_auto_resumed(self):
        sim = FakeRuntime(events=[(1, 5, 1, (7,)), (2, 5, 2, (7,))])
        with self.assertRaisesRegex(ExportError, "unexpected_exec"):
            self.run_capture(sim)
        self.assertEqual(sim.actions.count(("continue", 1)), 1)
        self.assertFalse(sim.reads)

    def test_cancel_between_salt_and_secret_stops_reads(self):
        sim = FakeRuntime(reasons=(3,), resolves_at=0)
        def cancelled():
            if sim.reads:
                raise ExportError("cancelled")
        with self.assertRaisesRegex(ExportError, "cancelled"):
            self.run_capture(sim, cancel_check=cancelled)
        self.assertEqual([pointer for _, pointer, _ in sim.reads], [20])
        self.assertIn(("detach",), sim.actions)

    def test_memory_read_cap_enforced(self):
        sim = FakeRuntime(reasons=(3,), resolves_at=0, second_key=False,
                          events=[(i, 5, i + 2, (3,)) for i in range(1, 120)])
        with self.assertRaisesRegex(ExportError, "capture_resource_limit"):
            self.run_capture(sim)
        self.assertEqual(len(sim.reads), 128)
        self.assertIn(("destroy",), sim.actions)

    def test_detach_failure_requires_supervised_exit_no_destroy(self):
        sim = FakeRuntime(detach_ok=False)
        with self.assertRaises(runtime.ManualDetachRequired) as caught:
            self.run_capture(sim)
        self.assertNotIn(("destroy",), sim.actions)
        reads = len(sim.reads)
        caught.exception.supervise(NS(manual_exit_required=lambda: setattr(sim, "state", 10)))
        self.assertEqual(len(sim.reads), reads)
        self.assertIn(("destroy",), sim.actions)

    def test_owner_change_never_detaches_foreign_process(self):
        sim = FakeRuntime()
        def guard():
            if sim.now >= 1:
                sim.owner = 999
        with self.assertRaises(runtime.ManualDetachRequired) as caught:
            self.run_capture(sim, check_external=guard)
        self.assertFalse(sim.reads)
        self.assertNotIn(("detach",), sim.actions)
        caught.exception.supervise(NS(manual_exit_required=lambda: setattr(sim, "state", 10)))

    def test_supervision_ui_interrupt_or_error_cannot_release_live_debugger(self):
        for error in (KeyboardInterrupt(), RuntimeError("synthetic UI failure")):
            with self.subTest(error=type(error).__name__):
                sim = FakeRuntime(detach_ok=False)
                with self.assertRaises(runtime.ManualDetachRequired) as caught:
                    self.run_capture(sim)
                actions_before, reads_before = list(sim.actions), list(sim.reads)
                prompts = []
                def prompt():
                    self.assertNotIn(("destroy",), sim.actions)
                    self.assertEqual(sim.reads, reads_before)
                    prompts.append(True)
                    if len(prompts) == 1:
                        raise error
                    sim.state = 10
                with patch.object(runtime.time, "sleep"):
                    caught.exception.supervise(NS(manual_exit_required=prompt))
                self.assertEqual(len(prompts), 2)
                self.assertEqual(sim.actions, actions_before + [("destroy",)])

    def test_unknown_process_state_during_supervision_requires_verified_exit(self):
        sim = FakeRuntime(detach_ok=False)
        with self.assertRaises(runtime.ManualDetachRequired) as caught:
            self.run_capture(sim)
        original_state = sim.process.GetState
        queries = []
        def state():
            queries.append(True)
            if len(queries) == 1:
                raise RuntimeError("synthetic state failure")
            return original_state()
        sim.process.GetState = state
        def prompt():
            self.assertNotIn(("destroy",), sim.actions)
            sim.state = 10
        caught.exception.supervise(NS(manual_exit_required=prompt))
        self.assertEqual(len(queries), 2)
        self.assertIn(("destroy",), sim.actions)

    def test_breakpoint_module_entry_must_be_exact(self):
        module = NS(IsValid=lambda: True, GetUUIDString=lambda: "uuid",
                    GetFileSpec=lambda: NS(GetDirectory=lambda: "/usr/lib/system", GetFilename=lambda: "libcommonCrypto.dylib"))
        symbol = NS(IsValid=lambda: True, GetName=lambda: "CCKeyDerivationPBKDF",
                    GetStartAddress=lambda: NS(GetFileAddress=lambda: 123))
        address = NS(GetModule=lambda: module, GetSymbol=lambda: symbol, GetFileAddress=lambda: 123)
        location = NS(IsEnabled=lambda: True, IsResolved=lambda: True, GetAddress=lambda: address, GetLoadAddress=lambda: 1000)
        breakpoint = NS(IsValid=lambda: True, IsEnabled=lambda: True, GetNumLocations=lambda: 1,
                        GetLocationAtIndex=lambda i: location)
        self.assertEqual(runtime.breakpoint_identity(NS(LLDB_INVALID_ADDRESS=-1), breakpoint), ("uuid", 123))
        module.GetFileSpec = lambda: NS(GetDirectory=lambda: "/untrusted", GetFilename=lambda: "libcommonCrypto.dylib")
        self.assertIsNone(runtime.breakpoint_identity(NS(LLDB_INVALID_ADDRESS=-1), breakpoint))

    def test_frame_identity_mismatch_never_announces_or_reads(self):
        sim = FakeRuntime(reasons=(3,), resolves_at=0)
        sim.frame.GetPCAddress = lambda: NS(GetModule=lambda: NS(GetUUIDString=lambda: "foreign"), GetFileAddress=lambda: 123)
        with self.assertRaisesRegex(ExportError, "capture_pc_or_module_mismatch"):
            self.run_capture(sim)
        self.assertFalse(sim.reads)
        self.assertFalse(sim.announcements)

    def test_pbkdf_call_cap_even_without_memory_reads(self):
        sim = FakeRuntime(reasons=(3,), resolves_at=0,
                          events=[(i / 100, 5, i + 2, (3,)) for i in range(1, 260)])
        with patch.object(runtime, "candidate_keys", return_value={}):
            with self.assertRaisesRegex(ExportError, "capture_resource_limit"):
                self.run_capture(sim)
        self.assertFalse(sim.reads)
        self.assertEqual(sum(action[0] == "continue" for action in sim.actions), 256)
