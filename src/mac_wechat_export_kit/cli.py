"""Public commands: read-only plan/export/verify and interactive guide/recover."""

import argparse
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .cipher import CipherDB, load_keys, load_library
from .exporter import export_conversation, verify_output
from .safety import ExportError, private_json, scoped_databases


class PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default errors echo unknown values, which may be secrets.
        print(json.dumps({"status": "stopped", "error_code": "invalid_arguments"}))
        raise SystemExit(2)


def run_export(config_path, output):
    config = private_json(config_path)
    fields = {"db_root", "key_file", "sqlcipher_library", "library_sha256", "contact_name",
              "expected_username", "self_username", "timezone"}
    if set(config) != fields or any(not isinstance(v, str) or not v for v in config.values()):
        raise ExportError("invalid_config_fields")
    if any(not Path(config[name]).is_absolute() for name in ("db_root", "key_file", "sqlcipher_library")):
        raise ExportError("config_paths_must_be_absolute")
    ZoneInfo(config["timezone"])
    paths = scoped_databases(config["db_root"])
    destination = Path(output).absolute()
    root = Path(config["db_root"]).absolute()
    if destination == root or root in destination.parents:
        raise ExportError("output_must_be_outside_database_root")
    keys = load_keys(config["key_file"])
    lib = load_library(config["sqlcipher_library"], config["library_sha256"])

    def opener(relative):
        return CipherDB(lib, paths[relative], keys[relative])

    return export_conversation(opener, contact_name=config["contact_name"],
                               expected_username=config["expected_username"], self_username=config["self_username"],
                               timezone=config["timezone"], output=output)


def main(argv=None):
    parser = PrivateArgumentParser(description="指定分库、单会话的本地只读导出；需要已有 raw key。")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="使用私有配置导出单个一对一会话")
    export.add_argument("--config", required=True)
    export.add_argument("--output", required=True)
    verify = commands.add_parser("verify", help="核对本地导出产物摘要、计数、ID 与排序")
    verify.add_argument("--output", required=True)
    plan_parser = commands.add_parser("plan", help="只读环境预检与操作计划；不取钥或改签名")
    plan_parser.add_argument("--config", required=True)
    plan_parser.add_argument("--bootstrap-only", action="store_true", help="核对仅取钥与恢复模式；仍报告完整导出缺失的依赖")
    guide_parser = commands.add_parser("guide", help="仅本机交互确认后的完整取钥、恢复和导出引导")
    guide_parser.add_argument("--config", required=True)
    guide_parser.add_argument("--bootstrap-only", action="store_true", help="完成取钥、验证和恢复后停止，不读取会话或导出")
    recovery_parser = commands.add_parser("recover", help="仅恢复已有会话，不取钥、不签名、不导出")
    recovery_parser.add_argument("--state", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            result = run_export(args.config, args.output)
        elif args.command == "verify":
            result = verify_output(args.output)
        else:
            from .bootstrap import TerminalUI, guide, load_setup, plan, recover
            from .mac_host import MacHost
            if args.command == "recover":
                ui = TerminalUI()  # Reject noninteractive use before any native operation.
                result = recover(args.state, MacHost(), ui)
            elif args.command == "guide":
                ui = TerminalUI()
                result = guide(load_setup(args.config), MacHost(), ui, bootstrap_only=args.bootstrap_only)
            else:
                result = plan(load_setup(args.config), MacHost(), bootstrap_only=args.bootstrap_only)
        print(json.dumps({"status": "ok", **result}, ensure_ascii=False))
        return 0
    except Exception as error:
        # Only our fixed codes may cross the console boundary. Never str(OSError),
        # JSONDecodeError, native SQL errors, user content, paths, or key material.
        code = str(error) if isinstance(error, ExportError) else "operation_failed"
        print(json.dumps({"status": "stopped", "error_code": code}))
        return 2
