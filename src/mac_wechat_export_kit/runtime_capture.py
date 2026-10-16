# SPDX-License-Identifier: MIT
# Adapted from reviewed capture15_once.py and cwd_comparison_once.py.
# Copyright (c) 2026 mac-wechat-export-kit contributors
"""One launched arm64 inferior; never attach, scan memory, or force-kill."""

from dataclasses import dataclass, field
import importlib
from pathlib import Path
import signal
import sys
import time

from .capture_policy import candidate_keys, validate_pages
from .safety import DATABASES, ExportError

TERMINAL_NAMES = ("eStateExited", "eStateDetached", "eStateInvalid", "eStateUnloaded")


def load_api(path):
    path = str(Path(path).resolve(strict=True))
    sys.path.insert(0, path)
    try:
        api = importlib.import_module("lldb")
    finally:
        sys.path.remove(path)
    origin = Path(api.__file__).resolve()
    if Path(path) not in origin.parents:
        raise ExportError("lldb_module_origin_mismatch")
    for name in ("SBDebugger", "SBLaunchInfo", "SBError", "SBEvent", "SBCommandReturnObject"):
        if not hasattr(api, name):
            raise ExportError("lldb_api_unavailable")
    return api


class Budget:
    def __init__(self, seconds=120, clock=time.monotonic):
        if not 1 <= seconds <= 120:
            raise ExportError("capture_timeout_out_of_bounds")
        self.seconds, self.clock, self.end = seconds, clock, None

    def __enter__(self):
        self.end = self.clock() + self.seconds
        self.previous = signal.signal(signal.SIGALRM, self.expired)
        signal.setitimer(signal.ITIMER_REAL, self.seconds)
        return self

    def expired(self, *_):
        raise ExportError("capture_deadline")

    def check(self):
        if self.end is None or self.clock() >= self.end:
            raise ExportError("capture_deadline")

    def __exit__(self, *args):
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, self.previous)


def breakpoint_identity(api, breakpoint):
    if not breakpoint.IsValid() or not breakpoint.IsEnabled() or breakpoint.GetNumLocations() != 1:
        return None
    location = breakpoint.GetLocationAtIndex(0)
    if not location.IsEnabled() or not location.IsResolved():
        return None
    address = location.GetAddress()
    module, symbol = address.GetModule(), address.GetSymbol()
    if not module.IsValid() or not symbol.IsValid():
        return None
    spec = module.GetFileSpec()
    if str(Path(spec.GetDirectory() or "") / (spec.GetFilename() or "")) != "/usr/lib/system/libcommonCrypto.dylib":
        return None
    if (not module.GetUUIDString() or symbol.GetName() not in ("CCKeyDerivationPBKDF", "_CCKeyDerivationPBKDF")
            or address.GetFileAddress() != symbol.GetStartAddress().GetFileAddress()
            or location.GetLoadAddress() == api.LLDB_INVALID_ADDRESS):
        return None
    return module.GetUUIDString(), address.GetFileAddress()


def stop_kind(api, process, breakpoint, initial_allowed):
    relevant = [thread for thread in process if thread.GetStopReason() not in (api.eStopReasonNone, api.eStopReasonInvalid)]
    if not relevant:
        return "pending_metadata"
    if all(t.GetStopReason() == api.eStopReasonExec for t in relevant):
        if initial_allowed:
            return "initial_exec"
        raise ExportError("unexpected_exec_no_resume")
    if any(t.GetStopReason() != api.eStopReasonBreakpoint for t in relevant):
        raise ExportError("unexpected_stop_no_resume")
    for thread in relevant:
        count = thread.GetStopReasonDataCount()
        ids = [thread.GetStopReasonDataAtIndex(i) for i in range(0, count, 2)]
        if count % 2 or not ids or any(value != breakpoint.GetID() for value in ids):
            raise ExportError("unowned_breakpoint_no_resume")
    return "owned_breakpoint"


@dataclass
class CaptureResult:
    keys: dict = field(default_factory=dict, repr=False)
    report: dict = field(default_factory=dict)


class ManualDetachRequired(Exception):
    """Retains ownership; the caller must supervise manual exit before returning."""
    def __init__(self, api, debugger, target, process):
        super().__init__("manual_debugger_cleanup_required")
        self.api, self.debugger, self.target, self.process = api, debugger, target, process

    def supervise(self, ui):
        terminal = tuple(getattr(self.api, name) for name in TERMINAL_NAMES)
        # No more ReadMemory, register reads, or Continue calls in recovery.
        # Explicit human-paced recovery, not an autonomous background wait loop.
        while True:
            try:
                if not self.process.IsValid() or self.process.GetState() in terminal:
                    break
            except (Exception, KeyboardInterrupt):
                pass  # Unknown state is not evidence that the owned process exited.
            try:
                ui.manual_exit_required()
            except (Exception, KeyboardInterrupt):
                # UI interruption must not unwind into normal app restoration or
                # a debugger destructor while a live inferior is still owned.
                try:
                    time.sleep(0.25)
                except KeyboardInterrupt:
                    pass
        self.api.SBDebugger.Destroy(self.debugger)


def release_debugger(api, debugger, target, process, owner=None):
    deleted = False
    try:
        target.DeleteAllBreakpoints()
        deleted = target.GetNumBreakpoints() == 0
    except Exception:
        pass
    terminal = tuple(getattr(api, name) for name in TERMINAL_NAMES)
    if process is None:
        process = target.GetProcess()
    if process.IsValid() and owner is not None and process.GetUniqueID() != owner:
        raise ManualDetachRequired(api, debugger, target, process)
    inactive = not process.IsValid() or process.GetState() in terminal
    if not inactive:
        try:
            error = process.Detach(False)
            inactive = error.Success() and process.GetState() in terminal
        except Exception:
            inactive = False
    if not inactive:
        raise ManualDetachRequired(api, debugger, target, process)
    api.SBDebugger.Destroy(debugger)
    if not deleted:
        raise ExportError("breakpoint_cleanup_unverified")


def capture(api, executable, pages, environment, *, check_external, verify_owned,
            announce, reserve_launch, cancel_check=lambda: None, budget=None):
    validate_pages(pages)
    budget = budget or Budget()
    debugger = api.SBDebugger.Create(False)
    debugger.SkipLLDBInitFiles(True)
    debugger.SetAsync(True)
    target = process = breakpoint = owner = None
    found, resumed, identity = {}, set(), None
    report = {"launches": 0, "pbkdf_calls": 0, "memory_reads": 0, "memory_bytes": 0,
              "startup_wait_samples": 0, "initial_exec_resumes": 0, "ready_for_user_login": False}
    try:
        target = debugger.CreateTarget(str(executable))
        if not target.IsValid() or not target.GetTriple().startswith("arm64"):
            raise ExportError("unsupported_debug_target")
        for command in ("settings set target.inherit-env false", "settings set target.skip-prologue false"):
            result = api.SBCommandReturnObject()
            debugger.GetCommandInterpreter().HandleCommand(command, result)
            if not result.Succeeded():
                raise ExportError("debugger_configuration_failed")
        breakpoint = target.BreakpointCreateByName("CCKeyDerivationPBKDF", "libcommonCrypto.dylib")
        if not breakpoint.IsValid() or not breakpoint.IsEnabled():
            raise ExportError("capture_breakpoint_invalid")
        launch = api.SBLaunchInfo([])
        launch.SetExecutableFile(api.SBFileSpec(str(executable)), True)
        launch.SetEnvironmentEntries([key + "=" + value for key, value in sorted(environment.items())], False)
        launch.SetWorkingDirectory(str(executable.parent))
        launch.SetLaunchFlags(2 | 512 | 128 | 16384)  # Pinned Apple launch configuration; see BOOTSTRAP.md.
        launch.SetDetachOnError(True)
        for descriptor in (0, 1, 2):
            launch.AddSuppressFileAction(descriptor, descriptor == 0, descriptor != 0)
        check_external()
        with budget:
            reserve_launch()  # One exclusive marker, never cleared on failure.
            budget.check()
            report["launches"] = 1
            error = api.SBError()
            process = target.Launch(launch, error)
            budget.check()
            if error.Fail() or not process.IsValid():
                raise ExportError("launch_failed_no_retry")
            owner = process.GetUniqueID()
            verify_owned(process.GetProcessID(), executable)
            listener, seen_running, next_guard = debugger.GetListener(), False, 0

            def check():
                budget.check()
                cancel_check()
                if process.GetUniqueID() != owner:
                    raise ExportError("process_identity_changed")

            def resume(stop_id):
                check()
                if process.GetState() != api.eStateStopped or process.GetStopID() != stop_id or stop_id in resumed:
                    return False
                if process.Continue().Fail():
                    raise ExportError("resume_failed_no_retry")
                resumed.add(stop_id)
                check()
                return True

            while set(found) != set(DATABASES):
                check()
                if budget.clock() >= next_guard:
                    check_external()
                    check()
                    next_guard = budget.clock() + 0.5
                state = process.GetState()
                if state in tuple(getattr(api, name) for name in TERMINAL_NAMES):
                    raise ExportError("process_ended_before_complete")
                if state in (api.eStateCrashed, api.eStateSuspended):
                    raise ExportError("unexpected_process_state")
                current = breakpoint_identity(api, breakpoint)
                if current is not None:
                    if identity is not None and identity != current:
                        raise ExportError("breakpoint_identity_changed")
                    identity = current
                if state == api.eStateRunning:
                    seen_running = True
                    if current is not None and not report["ready_for_user_login"]:
                        report["ready_for_user_login"] = True
                        announce("ready_for_user_login")
                if state == api.eStateStopped and process.GetStopID() not in resumed:
                    stop_id = process.GetStopID()
                    kind = stop_kind(api, process, breakpoint, not resumed and not seen_running and not report["ready_for_user_login"])
                    check()
                    if kind == "initial_exec":
                        if resume(stop_id):
                            report["initial_exec_resumes"] += 1
                    elif kind == "pending_metadata" or current is None:
                        report["startup_wait_samples"] += 1
                    else:
                        verify_owned(process.GetProcessID(), executable)
                        frames = []
                        for thread in process:
                            if thread.GetStopReason() in (api.eStopReasonNone, api.eStopReasonInvalid):
                                continue
                            frame = thread.GetFrameAtIndex(0)
                            address = frame.GetPCAddress()
                            if (address.GetModule().GetUUIDString(), address.GetFileAddress()) != identity:
                                raise ExportError("capture_pc_or_module_mismatch")
                            frames.append(frame)
                        if not report["ready_for_user_login"]:
                            report["ready_for_user_login"] = True
                            announce("ready_for_user_login")

                        def read_memory(address, length):
                            check()
                            if (process.GetState() != api.eStateStopped or process.GetStopID() != stop_id
                                    or not 0 < length <= 256 or not 0 < address < 2 ** 64):
                                raise ExportError("memory_read_context_invalid")
                            if report["memory_reads"] >= 128 or report["memory_bytes"] + length > 32768:
                                raise ExportError("capture_resource_limit")
                            report["memory_reads"] += 1
                            report["memory_bytes"] += length
                            error = api.SBError()
                            data = process.ReadMemory(address, length, error)
                            check()
                            if error.Fail() or len(data) != length:
                                raise ExportError("bounded_memory_read_failed")
                            return bytes(data)

                        for frame in frames:
                            check()
                            if report["pbkdf_calls"] >= 256:
                                raise ExportError("capture_resource_limit")
                            arguments = []
                            for index in range(7):
                                register, error = frame.FindRegister("x" + str(index)), api.SBError()
                                if not register.IsValid() or register.GetError().Fail():
                                    raise ExportError("argument_register_unavailable")
                                arguments.append(register.GetValueAsUnsigned(error, 0))
                                if error.Fail():
                                    raise ExportError("argument_register_read_failed")
                            report["pbkdf_calls"] += 1
                            found.update(candidate_keys(arguments, pages, read_memory, check))
                        if set(found) != set(DATABASES):
                            resume(stop_id)
                if set(found) != set(DATABASES):
                    listener.WaitForEvent(1, api.SBEvent())
            check()
        return CaptureResult(found, report)
    finally:
        # If Launch raises after creating a process, release_debugger uses
        # target.GetProcess(). No secret reads or automatic retry in cleanup.
        if target is not None and target.IsValid():
            release_debugger(api, debugger, target, process, owner)
        else:
            api.SBDebugger.Destroy(debugger)
