"""Minimal synthetic LLDB API. No native imports, subprocess, or app access."""

from pathlib import Path
from types import SimpleNamespace as NS

from mac_wechat_export_kit.safety import DATABASES, ExportError
from test_capture_policy import synthetic_page


class FakeRuntime:
    def __init__(self, *, events=None, reasons=(7,), resolves_at=2, detach_ok=True, second_key=True):
        self.now, self.stop, self.state, self.owner = 0, 1, 5, 42
        self.reasons, self.data = reasons, [7, 1]
        self.resolves_at, self.detach_ok = resolves_at, detach_ok
        self.actions, self.reads, self.announcements = [], [], []
        self.second_key = second_key
        self.keys = {DATABASES[0]: b"K" * 32, DATABASES[1]: b"L" * 32}
        self.pages = {name: synthetic_page(key, bytes([65 + index]) * 16)
                      for index, (name, key) in enumerate(self.keys.items())}
        self.events = list(events if events is not None else [(1, 6, 1, (7,)), (2, 6, 1, (7,)), (3, 5, 2, (3,)), (4, 5, 3, (3,))])
        self.error = lambda: NS(Fail=lambda: False, Success=lambda: True)
        api = NS(eStateInvalid=0, eStateUnloaded=1, eStateStopped=5, eStateRunning=6, eStateCrashed=8,
                 eStateDetached=9, eStateExited=10, eStateSuspended=11,
                 eStopReasonNone=1, eStopReasonInvalid=0, eStopReasonBreakpoint=3, eStopReasonExec=7,
                 SBError=self.error, SBEvent=lambda: None, SBFileSpec=lambda value: value,
                 SBCommandReturnObject=lambda: NS(Succeeded=lambda: True), LLDB_INVALID_ADDRESS=-1)
        self.api = api
        outer = self
        module = NS(GetUUIDString=lambda: "fixture-uuid")
        address = NS(GetModule=lambda: module, GetFileAddress=lambda: 123)
        def register(name):
            target = DATABASES[0] if self.stop < 3 or not self.second_key else DATABASES[1]
            args = [2, 10, 32, 20, 16, 5, 2]
            return NS(IsValid=lambda: True, GetError=self.error, GetValueAsUnsigned=lambda *args2: args[int(name[1:])])
        frame = NS(GetPCAddress=lambda: address, FindRegister=register)
        self.frame = frame
        self.thread = NS(GetStopReason=lambda: self.reasons[0], GetStopReasonDataCount=lambda: len(self.data),
                         GetStopReasonDataAtIndex=lambda i: self.data[i], GetFrameAtIndex=lambda i: frame)
        class Process:
            def IsValid(self): return True
            def GetUniqueID(self): return outer.owner
            def GetProcessID(self): return 1234
            def GetState(self): return outer.state
            def GetStopID(self): return outer.stop
            def __iter__(self):
                return iter([NS(GetStopReason=lambda reason=reason: reason,
                                GetStopReasonDataCount=lambda: len(outer.data), GetStopReasonDataAtIndex=lambda i: outer.data[i],
                                GetFrameAtIndex=lambda i: frame) for reason in outer.reasons])
            def Continue(self):
                outer.actions.append(("continue", outer.stop)); outer.state = 6
                return outer.error()
            def ReadMemory(self, pointer, length, error):
                outer.reads.append((outer.now, pointer, length))
                target = DATABASES[0] if outer.stop < 3 or not outer.second_key else DATABASES[1]
                return bytes(x ^ 0x3a for x in outer.pages[target][:16]) if pointer == 20 else outer.keys[target]
            def Detach(self, keep_stopped):
                outer.actions.append(("detach",))
                if outer.detach_ok:
                    outer.state = 9
                return NS(Success=lambda: outer.detach_ok)
        self.process = Process()
        self.breakpoint = NS(IsValid=lambda: True, IsEnabled=lambda: True, GetID=lambda: 7)
        def launch(info, error):
            self.actions.append(("launch",)); return self.process
        def delete():
            self.actions.append(("delete_breakpoints",))
        self.target = NS(IsValid=lambda: True, GetTriple=lambda: "arm64-apple-macosx", Launch=launch,
                         BreakpointCreateByName=lambda *args: self.breakpoint, DeleteAllBreakpoints=delete,
                         GetNumBreakpoints=lambda: 0, GetProcess=lambda: self.process)
        def wait(seconds, event):
            self.actions.append(("wait",))
            if self.events:
                self.now, self.state, self.stop, self.reasons = self.events.pop(0)
            else:
                self.now += 1
        debugger = NS(SkipLLDBInitFiles=lambda value: None, SetAsync=lambda value: None,
                      CreateTarget=lambda path: self.target, GetListener=lambda: NS(WaitForEvent=wait),
                      GetCommandInterpreter=lambda: NS(HandleCommand=lambda *args: None))
        api.SBDebugger = NS(Create=lambda value: debugger, Destroy=lambda value: self.actions.append(("destroy",)))
        api.SBLaunchInfo = lambda args: NS(SetExecutableFile=lambda *args: None, SetEnvironmentEntries=lambda *args: None,
                                         SetWorkingDirectory=lambda *args: None, SetLaunchFlags=lambda *args: None,
                                         SetDetachOnError=lambda *args: None, AddSuppressFileAction=lambda *args: None)
        self.budget = NS(clock=lambda: self.now)
        class FakeBudget:
            clock = lambda unused: outer.now
            def __enter__(unused):
                outer.actions.append(("start_budget",)); outer.deadline = outer.now + 120; return unused
            def check(unused):
                if outer.now >= outer.deadline:
                    raise ExportError("capture_deadline")
            def __exit__(unused, *args):
                outer.actions.append(("end_budget",))
        self.budget = FakeBudget()

    def identity(self, *args):
        return ("fixture-uuid", 123) if self.now >= self.resolves_at else None
