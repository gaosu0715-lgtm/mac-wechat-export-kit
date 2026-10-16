"""Visible, consent-gated workflow; real operations are injected behind MacHost."""

import json
import hashlib
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from .capture_policy import validate_pages, verify_raw_key
from .cipher import CipherDB, load_keys, load_library
from .runtime_capture import ManualDetachRequired, capture, load_api
from .safety import DATABASES, ExportError, private_json, private_text, scoped_databases, sql_text
from .session import Session

SETUP_FIELDS = {"app_path", "db_root", "state_dir", "sqlcipher_library", "library_sha256",
                "contact_name", "expected_username", "self_username", "timezone"}
PLAN = {"stages": ["read_only_preflight", "local_owner_consent", "user_quits_original",
                   "copy_and_sign_main_only", "one_bounded_debug_launch", "raw_key_authentication",
                   "user_quits_copy_and_integrity_restore", "user_confirms_original", "confirm_unique_contact_binding", "read_only_export"],
        "capture_seconds_max": 120, "memory_reads_max": 128, "memory_bytes_max": 32768,
        "pbkdf_calls_max": 256, "databases": list(DATABASES), "automatic_retry": False,
        "application_quit_requests": False, "user_menu_exit_required": True,
        "system_security_changes": False, "upload": False}


def load_setup(path):
    config = private_json(path)
    if set(config) != SETUP_FIELDS or any(not isinstance(v, str) for v in config.values()):
        raise ExportError("invalid_setup_fields")
    if any(not value for name, value in config.items() if name not in {"expected_username", "self_username"}):
        raise ExportError("invalid_setup_fields")
    for name in ("app_path", "db_root", "state_dir", "sqlcipher_library"):
        if not Path(config[name]).is_absolute() or any(ord(ch) < 32 for ch in config[name]):
            raise ExportError("setup_requires_absolute_paths")
    if not Path(config["state_dir"]).name.startswith("private-"):
        raise ExportError("session_name_must_start_private")
    if (config["expected_username"] and config["expected_username"] == config["self_username"]
            or config["expected_username"].endswith("@chatroom")):
        raise ExportError("invalid_one_to_one_binding")
    ZoneInfo(config["timezone"])
    return config


class TerminalUI:
    def __init__(self):
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise ExportError("interactive_local_terminal_required")

    def show_plan(self, config):
        print("将只处理当前用户明确选择的本机账号与两个库。请核对下列本地范围：", flush=True)
        # Escaped display only on an interactive local terminal. Never key values.
        print(json.dumps({name: config[name] for name in ("app_path", "db_root", "state_dir", "contact_name",
                                                         "expected_username", "self_username")}, ensure_ascii=False), flush=True)
        print("临时副本会共享原账号的容器和应用组；登录/同步可能写入原账号数据，可能被客户端察觉。\n"
              "只改副本主应用签名，保留沙盒、Hardened Runtime、嵌套厂商签名和 application-groups。\n"
              "取钥只限一次、最多 120 秒；Ctrl-C 或 cancel.request 可中止采集，之后仍须完成恢复。\n"
              "不得关闭 SIP 或修改系统安全设置；权限不足时停止。没有后台采集、上传或自动重试。", flush=True)

    def confirm(self, stage):
        prompts = {
            "consent": "确认这是你自己已登录过的本机账号，并同意上述本轮计划的副本、一次取钥、恢复及后续步骤；输入：同意本机取钥",
            "quit_original": "请用原版微信菜单正常退出，保存草稿；完成后输入：原版已退出",
            "quit_copy": "请核对本次临时副本窗口，通过其菜单正常退出并保存草稿；不要退出已恢复的原版。完成后输入：副本已退出",
            "restored": "请在原版界面确认账号与功能正常；确认后输入：原版已恢复",
            "recovery": "仅核验本次副本已由你正常退出，再核对原版并按需启动；不取钥、不签名、不导出。输入：只做恢复",
        }
        expected = {"consent": "同意本机取钥", "quit_original": "原版已退出", "quit_copy": "副本已退出",
                    "restored": "原版已恢复", "recovery": "只做恢复"}
        print(prompts[stage] + "（其他输入或 Ctrl-C 取消）", flush=True)
        try:
            answer = input().strip()
        except (EOFError, KeyboardInterrupt):
            raise ExportError("cancelled") from None
        if answer != expected[stage]:
            raise ExportError("cancelled")

    def announce(self, stage):
        messages = {"preflight": "进行只读预检；没有启动微信或读取数据库内容。",
                    "bootstrap_only": "本次只取钥、验证与恢复：不解析联系人、不读取会话表、不导出。",
                    "preparing": "准备并校验临时副本；只签主应用一次。",
                    "capturing": "开始单次限时启动；请等待“取钥已就绪”再操作登录。",
                    "ready_for_user_login": "取钥已就绪：请现在在临时副本中进入自己的账号，并完成所需手机确认。",
                    "restoring": "采集已停止，正在核验副本退出情况、原版完整性并恢复。",
                    "manual_copy_exit": "本次副本仍有进程。工具不会发送退出请求或强制结束应用，请通过副本菜单正常退出。无法区分窗口时先停止，不猜测。",
                    "exporting": "从指定两库只读导出已绑定的单个会话。",
                    "manual_recovery": "自动恢复未完成。不要重跑取钥；请正常退出副本，再使用 recover。"}
        print(messages[stage], flush=True)

    def manual_exit_required(self):
        print("采集已停止，调试器尚未安全脱离。请保持此终端打开，在临时副本菜单正常退出，然后回车核验。\n"
              "这里不会再读内存、继续进程或强制结束应用。Ctrl-C 只取消采集，不能代替恢复。", flush=True)
        try:
            input()
        except (KeyboardInterrupt, EOFError):
            # Preserve debugger ownership; never allow its destructor to kill a live app.
            import time
            time.sleep(1)

    def show_recovery(self, config):
        print("只恢复这次私有会话，不重新采集。请核对：", flush=True)
        print(json.dumps({name: config[name] for name in ("app_path", "state_dir")}, ensure_ascii=False), flush=True)

    def show_copy_exit(self, session):
        # Exact local scope without inspecting window contents or revealing keys.
        print("请核对本次副本位置；不要重新打开它，不要操作其他微信：", flush=True)
        print(json.dumps({"temporary_copy": str(session.active), "disabled_copy": str(session.disabled),
                          "original_app": session.record["config"]["app_path"]}, ensure_ascii=False), flush=True)

    def confirm_binding(self, config, binding):
        print("只读解析到唯一联系人；请核对本机选定昵称/备注与身份绑定。不会显示聊天正文：", flush=True)
        print(json.dumps({"contact_name": config["contact_name"], **binding}, ensure_ascii=False), flush=True)
        print("确认这是你要导出的单个一对一会话，输入：确认此联系人（其他输入取消）", flush=True)
        try:
            answer = input().strip()
        except (EOFError, KeyboardInterrupt):
            raise ExportError("cancelled") from None
        if answer != "确认此联系人":
            raise ExportError("cancelled")


def read_selected_pages(root):
    pages = {}
    for relative, path in scoped_databases(root).items():
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            pages[relative] = stream.read(4096)
    validate_pages(pages)
    return pages


def validate_and_save_keys(session, keys, before, *, library_loader=load_library):
    config = session.record["config"]
    after = read_selected_pages(config["db_root"])
    if after != before:
        raise ExportError("selected_database_pages_changed")
    if set(keys) != set(DATABASES) or any(not verify_raw_key(keys[name], after[name]) for name in DATABASES):
        raise ExportError("incomplete_or_unauthenticated_keys")
    library = library_loader(config["sqlcipher_library"], config["library_sha256"])
    paths = scoped_databases(config["db_root"])
    for name in DATABASES:
        with CipherDB(library, paths[name], keys[name].hex()):
            pass  # Read-only schema operation confirms actual SQLCipher interpretation.
    with private_text(session.root / "keys.json") as stream:
        json.dump({"keys": {name: {"enc_key": keys[name].hex()} for name in DATABASES}}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    session.save(keys_verified=True, capture_complete=True, stage="keys_verified")


def native_capture(host, session, pages, ui):
    host.verify_candidate(session, session.disabled)
    host.assert_original_unchanged(session)
    original = Path(session.record["config"]["app_path"])
    if host.app_processes(original):
        raise ExportError("quit_original_normally_first")
    session.check_cancelled()
    session.disabled.rename(session.active)
    session.save(stage="capturing")
    api = load_api(session.record["baseline"]["lldb_python"])
    def guard():
        session.check_cancelled()
        host.guard(original, session.active)
    def reserve():
        session.reserve("launch")
        session.save(launches=1)
    return capture(api, session.active / "Contents/MacOS/WeChat", pages, host.env,
                   check_external=guard, cancel_check=session.check_cancelled, verify_owned=host.verify_owned,
                   announce=ui.announce, reserve_launch=reserve)


def resolve_export_binding(config, key_path):
    """Resolve only the exact display-name match and selected table participants.

    No account discovery, other conversation body reads, or first-match choice.
    Empty IDs in setup permit a genuine start without pre-decrypting contact.db.
    """
    keys = load_keys(key_path)
    library = load_library(config["sqlcipher_library"], config["library_sha256"])
    paths = scoped_databases(config["db_root"])
    with CipherDB(library, paths[DATABASES[0]], keys[DATABASES[0]]) as contacts:
        rows = contacts.query("SELECT username FROM contact WHERE nick_name=" + sql_text(config["contact_name"])
                              + " OR remark=" + sql_text(config["contact_name"]))
    if len(rows) != 1 or not rows[0]["username"] or rows[0]["username"].endswith("@chatroom"):
        raise ExportError("contact_missing_ambiguous_or_group")
    username = rows[0]["username"]
    if config["expected_username"] and config["expected_username"] != username:
        raise ExportError("contact_binding_changed")
    table = '"Msg_' + hashlib.md5(username.encode()).hexdigest() + '"'
    with CipherDB(library, paths[DATABASES[1]], keys[DATABASES[1]]) as messages:
        participants = messages.query("SELECT DISTINCT n.user_name FROM " + table
                                      + " m LEFT JOIN Name2Id n ON n.rowid=m.real_sender_id")
    account_directory = Path(config["db_root"]).parent.name
    def matches_account(name):
        return name and (account_directory == name or account_directory.startswith(name + "_"))
    self_username = config["self_username"]
    if not self_username:
        candidates = {row["user_name"] for row in participants if row["user_name"] != username and matches_account(row["user_name"])}
        if len(candidates) != 1:
            raise ExportError("self_identity_requires_explicit_confirmation")
        self_username = candidates.pop()
    if not matches_account(self_username) or self_username == username:
        raise ExportError("self_account_directory_binding_mismatch")
    if any(row["user_name"] not in (None, username, self_username) for row in participants):
        raise ExportError("unexpected_conversation_participant")
    return {"expected_username": username, "self_username": self_username}


def plan(config, host, *, bootstrap_only=False):
    baseline = host.preflight(config)
    compression_available = baseline.get("zstandard_available", True)
    ready = bootstrap_only or compression_available
    stages = [stage for stage in PLAN["stages"] if not bootstrap_only
              or stage not in {"confirm_unique_contact_binding", "read_only_export"}]
    return {"supported": baseline["supported"], **PLAN, "live_actions_executed": False,
            "stages": stages, "export_requested": not bootstrap_only,
            "requested_mode": "bootstrap_only" if bootstrap_only else "capture_restore_and_export",
            "ready_for_live_guide": ready, "missing_dependencies": [] if ready else ["zstandard"],
            "zstandard_available": compression_available,
            "ready_for_full_export": compression_available,
            "full_export_missing_dependencies": [] if compression_available else ["zstandard"]}


def restore_session(session, host, ui):
    """One human exit handoff, then recovery only; never recapture or send quit."""
    # Migrate the current blocker of an older journal into durable history.
    if session.record.get("error_code") and not session.record.get("error_history"):
        session.save(error_history=[{"phase": "previous_run", "code": session.record["error_code"]}])
    session.save(cleanup_complete=False, copy_cleanup_complete=False,
                 original_integrity_unchanged=None, original_user_confirmed=False,
                 recovery_error_code=None, confirmation_error_code=None, stage="restoring")
    try:
        ui.announce("restoring")
        try:
            host.restore(session)
        except ExportError as error:
            if str(error) != "manual_copy_quit_required":
                raise
            session.save(stage="awaiting_copy_exit", manual_copy_exit_required=True)
            ui.announce("manual_copy_exit")
            ui.show_copy_exit(session)
            ui.confirm("quit_copy")
            # This is cleanup after an explicit human action, not a capture retry.
            host.restore(session)
    except (Exception, KeyboardInterrupt) as error:
        code = str(error) if isinstance(error, ExportError) else "cancelled" if isinstance(error, KeyboardInterrupt) else "restoration_failed"
        session.save(cleanup_complete=False, original_user_confirmed=False, stage="manual_recovery")
        session.record_error("recovery", code)
        ui.announce("manual_recovery")
        raise ExportError(code) from None
    session.save(recovery_error_code=None, error_code=session.record.get("workflow_error_code"))


def confirm_restored(session, ui):
    try:
        ui.confirm("restored")
    except (Exception, KeyboardInterrupt) as error:
        code = str(error) if isinstance(error, ExportError) else "cancelled" if isinstance(error, KeyboardInterrupt) else "original_confirmation_failed"
        session.save(original_user_confirmed=False, stage="awaiting_original_confirmation")
        session.record_error("confirmation", code)
        raise ExportError(code) from None
    session.save(original_user_confirmed=True, confirmation_error_code=None,
                 error_code=session.record.get("workflow_error_code"))


def guide(config, host, ui, *, capture_runner=native_capture, key_validator=validate_and_save_keys,
          binding_resolver=resolve_export_binding, export_runner=None, bootstrap_only=False):
    if export_runner is None:
        from .cli import run_export
        export_runner = run_export
    ui.announce("preflight")
    baseline = host.preflight(config)
    if not bootstrap_only and not baseline.get("zstandard_available", True):
        raise ExportError("zstandard_required_for_guide")
    ui.show_plan(config)
    if bootstrap_only:
        ui.announce("bootstrap_only")
    ui.confirm("consent")
    # Create the private journal after consent, before asking the user to quit.
    # A state-directory error cannot leave an already-quit original unrecorded.
    session = Session.create(config["state_dir"], config, baseline)
    session.save(export_requested=not bootstrap_only)
    failure = None
    try:
        ui.confirm("quit_original")
        if host.app_processes(Path(config["app_path"])):
            raise ExportError("quit_original_normally_first")
        session.check_cancelled()
        ui.announce("preparing")
        host.prepare(session)
        session.check_cancelled()
        pages = read_selected_pages(config["db_root"])
        ui.announce("capturing")
        result = capture_runner(host, session, pages, ui)
        session.save(capture_report=result.report)
        session.check_cancelled()
        key_validator(session, result.keys, pages)
    except ManualDetachRequired as held:
        session.save(stage="manual_debugger_recovery", error_code="manual_debugger_cleanup_required")
        failure = "manual_debugger_cleanup_required"
        held.supervise(ui)  # Stops all collection; do not Destroy a live attached inferior.
    except (Exception, KeyboardInterrupt) as error:
        failure = str(error) if isinstance(error, ExportError) else "cancelled" if isinstance(error, KeyboardInterrupt) else "bootstrap_failed"
    finally:
        if failure:
            session.record_error("workflow", failure)
        restore_session(session, host, ui)
    confirm_restored(session, ui)
    if failure:
        session.save(error_code=failure)
        raise ExportError(failure)
    session.check_cancelled()
    if bootstrap_only:
        session.save(stage="bootstrap_complete")
        return {"bootstrap_complete": True, "keys_verified": True, "cleanup_complete": True,
                "original_user_confirmed": True, "export_started": False}
    binding = binding_resolver(config, session.root / "keys.json")
    ui.confirm_binding(config, binding)
    session.save(binding=binding)
    export_config = {name: config[name] for name in ("db_root", "sqlcipher_library", "library_sha256", "contact_name",
                                                   "expected_username", "self_username", "timezone")}
    export_config.update(binding)
    export_config["key_file"] = str(session.root / "keys.json")
    export_path = session.root / "export-config.json"
    with private_text(export_path) as stream:
        json.dump(export_config, stream)
    ui.announce("exporting")
    try:
        summary = export_runner(export_path, session.root / "export")
    except Exception:
        session.save(stage="export_stopped", error_code="export_failed")
        raise ExportError("export_failed") from None
    session.save(export_complete=True, stage="complete")
    return {"workflow_complete": True, "keys_verified": True, "cleanup_complete": True,
            "original_user_confirmed": True, **summary}


def recover(state, host, ui):
    # Recovery never reads keys.json, database pages, or invokes capture/signing.
    session = Session.load(state)
    ui.show_recovery(session.record["config"])
    # Consent to recovery is separate from capture; no request to capture again.
    ui.confirm("recovery")
    restore_session(session, host, ui)
    confirm_restored(session, ui)
    return {"cleanup_complete": True, "capture_started": False, "export_started": False,
            "original_user_confirmed": True}
