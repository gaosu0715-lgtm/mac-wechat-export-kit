"""Read-only scan of this repository's publish candidates. No uploads or fixes."""

import ast
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {".gitignore", ".gitattributes", "README.md", "LICENSE", "NOTICE", "pyproject.toml", "requirements-optional.txt"}
TEMPLATES = {"examples/config.example.json", "examples/setup.example.json"}


def allowed(name):
    path = Path(name)
    if name in ROOT_FILES or name in TEMPLATES or name == ".github/workflows/ci.yml":
        return True
    return (path.parts[0] in {"src", "tests", "examples", "scripts"} and path.suffix == ".py"
            or path.parts[0] == "docs" and path.suffix == ".md")


def main():
    result = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    if result.returncode:
        print(json.dumps({"ok": False, "error": "local_git_repository_required"}))
        return 2
    names = sorted(set(result.stdout.decode("utf-8").strip("\0").split("\0")) - {""})
    failures = []
    ignored = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "--no-index", "--stdin", "-z"],
                             input=("\0".join(names) + "\0").encode(),
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    if ignored.returncode not in (0, 1):
        print(json.dumps({"ok": False, "error": "git_ignore_check_failed"}))
        return 2
    for name in ignored.stdout.decode("utf-8").strip("\0").split("\0"):
        if name:
            failures.append({"file": name, "code": "ignored_candidate"})
    checks = [
        ("personal_path", re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/")),
        ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
        ("service_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{24,})\b")),
        ("account_identifier", re.compile(r"\bwxid_[A-Za-z0-9]{6,}\b")),
        ("literal_raw_key", re.compile(r'''["']enc_key["']\s*:\s*["'][0-9a-fA-F]{64}["']''')),
    ]
    required = ROOT_FILES | TEMPLATES | {"docs/licenses/upstream-MIT.md"}
    for name in required - set(names):
        failures.append({"file": name, "code": "required_candidate_missing"})
    for name in names:
        if not allowed(name):
            failures.append({"file": name, "code": "unexpected_candidate_type"})
            continue
        path = ROOT / name
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
            failures.append({"file": name, "code": "not_regular_candidate"})
            continue
        if path.stat().st_size > 1024 * 1024:
            failures.append({"file": name, "code": "oversize_candidate"})
            continue
        text = path.read_text(encoding="utf-8")
        for code, pattern in checks:
            if pattern.search(text):
                failures.append({"file": name, "code": code})
        if path.suffix == ".py":
            try:
                ast.parse(text)
            except SyntaxError:
                failures.append({"file": name, "code": "python_syntax"})
    for template in TEMPLATES:
        config = json.loads((ROOT / template).read_text())
        for name, value in config.items():
            public_default = value == "UTC" or name == "app_path" and value == "/Applications/WeChat.app"
            blank_binding = template.endswith("setup.example.json") and name in {"self_username", "expected_username"} and value == ""
            if not isinstance(value, str) or not (public_default or blank_binding or value.startswith("<") and value.endswith(">")):
                failures.append({"file": template, "code": "template_not_placeholder_only"})
    staged = subprocess.run(["git", "-C", str(ROOT), "diff", "--cached", "--name-only"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    print(json.dumps({"ok": not failures, "candidate_count": len(names), "candidates": names,
                      "has_staged_changes": bool(staged.stdout.strip()), "failures": failures,
                      "scope": "heuristic scan; manual review required; no uploads"}, ensure_ascii=False, indent=2))
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
