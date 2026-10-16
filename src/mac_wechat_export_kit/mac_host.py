# SPDX-License-Identifier: MIT
# Adapted from reviewed signing_metadata.py / app_group_once.py /
# cwd_comparison_once.py. Copyright (c) 2026 mac-wechat-export-kit contributors.
"""Explicit macOS operations. Merely importing this module does nothing."""

import hashlib
import importlib.util
import os
from pathlib import Path
import platform
import plistlib
import re
import subprocess
import time

from .capture_policy import intended_entitlements
from .cipher import load_library
from .safety import ExportError, canonical, scoped_databases

SUPPORTED = {"os": "27.0.1", "version": "4.1.13", "build": "269602", "arch": "arm64"}


def trusted_lldb_path(module_path, developer_path):
    resolved, developer = Path(module_path).resolve(strict=True), Path(developer_path).resolve(strict=True)
    # Xcode's LLDB.framework lives in Contents/SharedFrameworks, a sibling of
    # Contents/Developer. Command Line Tools modules live under Developer itself.
    trusted = developer
    if developer.name == "Developer" and developer.parent.name == "Contents" and developer.parent.parent.suffix == ".app":
        trusted = developer.parent
    if trusted not in resolved.parents:
        raise ExportError("lldb_outside_selected_developer_tools")
    return resolved


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bundle_digest(app):
    excluded = {"Contents/MacOS/WeChat", "Contents/_CodeSignature/CodeResources"}
    digest, size, count, deadline = hashlib.sha256(), 0, 0, time.monotonic() + 180
    for path in sorted(app.rglob("*")):
        relative = path.relative_to(app).as_posix()
        if relative in excluded:
            continue
        count += 1
        if count > 50000 or time.monotonic() > deadline:
            raise ExportError("bundle_inventory_limit")
        digest.update(relative.encode() + b"\0")
        if path.is_symlink():
            link = os.readlink(path)
            if app not in path.resolve().parents:
                raise ExportError("bundle_external_link_rejected")
            digest.update(b"L" + link.encode())
        elif path.is_file():
            size += path.stat().st_size
            if size > 10 * 1024 ** 3:
                raise ExportError("bundle_inventory_limit")
            digest.update(b"F")
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    if time.monotonic() > deadline:
                        raise ExportError("bundle_inventory_limit")
                    digest.update(block)
        elif path.is_dir():
            digest.update(b"D")
        else:
            raise ExportError("bundle_special_file_rejected")
    return digest.hexdigest()


def parse_entitlements(text):
    if text.lstrip().startswith(("<?xml", "<plist")):
        result = plistlib.loads(text.encode())
        if not isinstance(result, dict):
            raise ExportError("unsupported_entitlements_document")
        return result
    lines = [line for line in text.splitlines() if line.strip()]
    def node(index):
        line = lines[index]
        depth, value = len(line) - len(line.lstrip("\t")), line.strip()
        if value.startswith("[String] "):
            return value[9:], index + 1
        if value in ("[Bool] true", "[Bool] false"):
            return value.endswith("true"), index + 1
        if value not in ("[Dict]", "[Array]"):
            raise ExportError("unsupported_entitlement_type")
        result, index = ({} if value == "[Dict]" else []), index + 1
        while index < len(lines) and len(lines[index]) - len(lines[index].lstrip("\t")) > depth:
            if isinstance(result, dict):
                token = lines[index].strip()
                if not token.startswith("[Key] ") or lines[index + 1].strip() != "[Value]":
                    raise ExportError("unsupported_entitlements_document")
                key = token[6:]
                if key in result:
                    raise ExportError("duplicate_entitlement")
                child, index = node(index + 2)
                result[key] = child
            else:
                child, index = node(index)
                result.append(child)
        return result, index
    try:
        result, end = node(0)
    except (IndexError, ValueError):
        raise ExportError("unsupported_entitlements_document") from None
    if end != len(lines) or not isinstance(result, dict):
        raise ExportError("unsupported_entitlements_document")
    return result


class MacHost:
    def __init__(self):
        import pwd
        name = pwd.getpwuid(os.geteuid()).pw_name
        # No inherited debugger injection settings, cloud/API keys, or credentials.
        self.env = {"HOME": str(Path.home()), "USER": name, "LOGNAME": name,
                    "LANG": "en_US.UTF-8", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "TMPDIR": "/tmp"}
        self.observer = None

    def command(self, args, timeout=10):
        return subprocess.run(args, env=self.env, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=timeout)

    def checked(self, args, timeout=10):
        result = self.command(args, timeout)
        if result.returncode:
            raise ExportError("native_command_failed")
        return result.stdout + result.stderr

    def processes(self):
        result = []
        for line in self.checked(["/bin/ps", "-axo", "pid=,uid=,comm="], 3).splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                result.append((int(parts[0]), int(parts[1]), parts[2]))
        return result

    def app_processes(self, app):
        prefix = str(app) + "/"
        return [(pid, uid, path) for pid, uid, path in self.processes() if path.startswith(prefix)]

    def original_running(self, app):
        processes = self.app_processes(app)
        if any(uid != os.geteuid() for _, uid, _ in processes):
            raise ExportError("original_process_owner_changed")
        if not processes:
            return False
        if not any(path == str(app / "Contents/MacOS/WeChat") for _, _, path in processes):
            raise ExportError("original_main_not_observed")
        return True

    def verify_owned(self, pid, executable):
        if (pid, os.geteuid(), str(executable)) not in self.processes():
            raise ExportError("owned_process_path_or_user_changed")

    def entitlements(self, app):
        result = self.command(["/usr/bin/codesign", "-d", "--entitlements", "-",
                               str(app / "Contents/MacOS/WeChat")])
        if result.returncode or not result.stdout.strip():
            raise ExportError("entitlements_unavailable")
        return parse_entitlements(result.stdout)

    def snapshot(self, app):
        self.checked(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], 30)
        metadata = self.checked(["/usr/bin/codesign", "-dvvv", str(app)])
        entitlements = self.entitlements(app)
        intended_entitlements(entitlements)
        if "TeamIdentifier=5A4RE8SF68" not in metadata or "Identifier=com.tencent.xinWeChat\n" not in metadata:
            raise ExportError("original_vendor_identity_mismatch")
        self.check_flags(app, original=True)
        return {"main": digest_file(app / "Contents/MacOS/WeChat"), "nested": bundle_digest(app),
                "signature": hashlib.sha256(metadata.encode()).hexdigest(), "entitlements": entitlements}

    def check_flags(self, app, original=False):
        for arch in ("arm64", "x86_64"):
            text = self.checked(["/usr/bin/codesign", "-dvv", "--arch", arch, str(app)])
            match = re.search(r"flags=(0x[0-9a-fA-F]+)\(", text)
            if not match or (int(match.group(1), 16) & 0x10000) == 0:
                raise ExportError("hardened_runtime_required")
            if not original and int(match.group(1), 16) != 0x10002:
                raise ExportError("candidate_signature_flags_changed")

    def guard(self, original, candidate=None):
        try:
            if self.observer is None:
                from .permission_windows import MacPermissionBackend, PermissionObserver
                self.observer = PermissionObserver(MacPermissionBackend(self.command))
            self.observer.check()
        except RuntimeError:
            raise ExportError("system_permission_observer_stopped") from None
        if candidate is not None and self.app_processes(original):
            raise ExportError("original_relaunched_during_capture")

    def preflight(self, config):
        if os.geteuid() == 0:
            raise ExportError("ordinary_user_required")
        if platform.system() != "Darwin" or platform.machine() != SUPPORTED["arch"]:
            raise ExportError("unsupported_platform_or_rosetta")
        if self.checked(["/usr/bin/sw_vers", "-productVersion"]).strip() != SUPPORTED["os"]:
            raise ExportError("unsupported_macos_version")
        if not re.search(r"System Integrity Protection status:\s*enabled\.", self.checked(["/usr/bin/csrutil", "status"])):
            raise ExportError("sip_enabled_required")
        app = canonical(config["app_path"], directory=True)
        with canonical(app / "Contents/Info.plist").open("rb") as stream:
            info = plistlib.load(stream)
        if (info.get("CFBundleIdentifier") != "com.tencent.xinWeChat"
                or info.get("CFBundleShortVersionString") != SUPPORTED["version"]
                or str(info.get("CFBundleVersion")) != SUPPORTED["build"]
                or info.get("CFBundleExecutable") != "WeChat"):
            raise ExportError("unsupported_wechat_version")
        root = canonical(config["db_root"], directory=True)
        parent = Path.home() / "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"
        if root.name != "db_storage" or root.parent.parent != parent:
            raise ExportError("account_not_explicit_current_user_location")
        if config["self_username"] and root.parent.name != config["self_username"] and not root.parent.name.startswith(config["self_username"] + "_"):
            raise ExportError("self_account_directory_binding_mismatch")
        scoped_databases(root)  # Paths only, no encrypted pages until live consent.
        state = Path(config["state_dir"])
        canonical(state.parent, directory=True)
        if state.exists() or state.is_symlink() or state == root or root in state.parents or app in state.parents:
            raise ExportError("new_separate_session_directory_required")
        for _, _, path in self.processes():
            if Path(path).name in ("lldb", "debugserver", "lldb-server") or "/WeChat-trial." in path:
                raise ExportError("existing_debug_session_refused")
            if Path(path).name == "WeChat" and not path.startswith(str(app) + "/"):
                raise ExportError("other_wechat_installation_running")
        self.guard(app)
        load_library(config["sqlcipher_library"], config["library_sha256"])
        lldb_path = self.checked(["/usr/bin/lldb", "-P"], 15).strip()
        developer = self.checked(["/usr/bin/xcode-select", "-p"]).strip()
        resolved = trusted_lldb_path(lldb_path, developer)
        from .runtime_capture import load_api
        load_api(resolved)  # Import/ABI check only, no debugger target or launch.
        return {"original": self.snapshot(app), "lldb_python": str(resolved), "supported": SUPPORTED,
                "zstandard_available": importlib.util.find_spec("zstandard") is not None}

    def assert_original_unchanged(self, session):
        if self.snapshot(Path(session.record["config"]["app_path"])) != session.record["baseline"]["original"]:
            session.save(original_integrity_unchanged=False)
            raise ExportError("original_integrity_changed")

    def prepare(self, session):
        app = Path(session.record["config"]["app_path"])
        self.assert_original_unchanged(session)
        if self.app_processes(app):
            raise ExportError("quit_original_normally_first")
        self.guard(app)
        self.checked(["/usr/bin/ditto", str(app), str(session.disabled)], 180)
        baseline = session.record["baseline"]["original"]
        if (digest_file(session.disabled / "Contents/MacOS/WeChat") != baseline["main"]
                or bundle_digest(session.disabled) != baseline["nested"]
                or self.entitlements(session.disabled) != baseline["entitlements"]):
            raise ExportError("copy_before_signing_mismatch")
        intended = intended_entitlements(baseline["entitlements"])
        from .safety import private_text
        entitlement_path = session.root / "copy-entitlements.plist"
        with private_text(entitlement_path) as stream:
            stream.write(plistlib.dumps(intended).decode())
        session.reserve("sign")
        session.save(signings=1, stage="signing")
        # Never --deep during signing; nested vendor signatures remain untouched.
        self.checked(["/usr/bin/codesign", "--force", "--sign", "-", "--options", "runtime", "--timestamp=none",
                      "--entitlements", str(entitlement_path), str(session.disabled)], 90)
        self.verify_candidate(session, session.disabled)
        session.save(candidate_main=digest_file(session.disabled / "Contents/MacOS/WeChat"), stage="prepared")
        self.assert_original_unchanged(session)

    def verify_candidate(self, session, app):
        app = canonical(app, directory=True)
        baseline = session.record["baseline"]["original"]
        if (self.entitlements(app) != intended_entitlements(baseline["entitlements"])
                or bundle_digest(app) != baseline["nested"]):
            raise ExportError("candidate_entitlements_or_nested_changed")
        expected = session.record.get("candidate_main")
        if expected and digest_file(app / "Contents/MacOS/WeChat") != expected:
            raise ExportError("candidate_main_changed")
        self.checked(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], 30)
        self.check_flags(app)

    def restore(self, session):
        # A repeat recovery must never inherit old success/confirmation flags.
        session.save(cleanup_complete=False, copy_cleanup_complete=False,
                     original_integrity_unchanged=None, original_user_confirmed=False)
        original = canonical(session.record["config"]["app_path"], directory=True)
        if (original == session.root or original in session.root.parents
                or session.root in original.parents):
            raise ExportError("recovery_path_overlap")
        self.assert_original_unchanged(session)
        session.save(original_integrity_unchanged=True)
        # Do not resolve an application by name, bundle ID, or AppleScript path.
        # The user quits the visible copy; this function only observes processes.
        for candidate in (session.active, session.disabled):
            if candidate.exists():
                canonical(candidate, directory=True)
            if self.app_processes(candidate):
                raise ExportError("manual_copy_quit_required")
        if session.active.exists():
            # Unregister only this temporary bundle before disabling it.
            register = "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
            self.checked([register, "-u", str(session.active)], 10)
            if session.disabled.exists():
                raise ExportError("disabled_copy_already_exists")
            if self.app_processes(session.active):
                raise ExportError("manual_copy_quit_required")
            session.active.rename(session.disabled)
        if self.app_processes(session.active) or self.app_processes(session.disabled):
            raise ExportError("manual_copy_quit_required")
        session.save(copy_cleanup_complete=True)
        session.save(original_integrity_unchanged=None)
        self.assert_original_unchanged(session)
        session.save(original_integrity_unchanged=True)
        if not self.original_running(original):
            subprocess.Popen([str(original / "Contents/MacOS/WeChat")], env=self.env,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            end = time.monotonic() + 10
            while time.monotonic() < end and not self.original_running(original):
                time.sleep(0.25)
        if not self.original_running(original):
            raise ExportError("original_launch_not_observed")
        session.save(cleanup_complete=True, original_integrity_unchanged=True, stage="restored")
