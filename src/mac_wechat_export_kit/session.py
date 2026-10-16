"""Private session journal; no key material or raw native errors in records."""

import json
import os
from pathlib import Path
import tempfile

from .safety import ExportError, canonical, new_output, private_json, private_text


class Session:
    def __init__(self, root, record):
        self.root, self.record = root, record

    @classmethod
    def create(cls, root, config, baseline):
        root = new_output(root)
        session = cls(root, {"schema_version": 1, "config": config, "baseline": baseline,
                             "stage": "consented", "launches": 0, "signings": 0,
                             "keys_verified": False, "capture_complete": False,
                             "cleanup_complete": False, "copy_cleanup_complete": False,
                             "original_integrity_unchanged": None, "original_user_confirmed": False,
                             "workflow_error_code": None, "recovery_error_code": None,
                             "confirmation_error_code": None, "error_history": [],
                             "export_complete": False})
        session.save()
        return session

    @classmethod
    def load(cls, root):
        root = canonical(root, directory=True)
        if root.stat().st_uid != os.geteuid() or root.stat().st_mode & 0o777 != 0o700:
            raise ExportError("session_directory_not_private")
        record = private_json(root / "session.json")
        if record.get("schema_version") != 1:
            raise ExportError("unsupported_session")
        if Path(record["config"]["state_dir"]) != root:
            raise ExportError("session_path_changed")
        return cls(root, record)

    def save(self, **fields):
        self.record.update(fields)
        fd, temporary = tempfile.mkstemp(prefix=".journal-", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self.record, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.root / "session.json")
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def reserve(self, name):
        # Exclusive marker is durable before the operation, including failure.
        with private_text(self.root / (name + "-used.json")) as stream:
            json.dump({"one_attempt": True}, stream)
            stream.flush()
            os.fsync(stream.fileno())

    def record_error(self, phase, code):
        # Fixed codes only, never raw exception messages or OS diagnostics.
        history = list(self.record.get("error_history", []))
        history.append({"phase": phase, "code": code})
        self.save(error_history=history, **{phase + "_error_code": code}, error_code=code)

    @property
    def active(self):
        return self.root / "WeChat-trial.app"

    @property
    def disabled(self):
        return self.root / "WeChat-trial.disabled"

    def check_cancelled(self):
        if (self.root / "cancel.request").exists():
            raise ExportError("cancelled")
