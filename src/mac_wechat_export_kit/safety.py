"""Explicit paths, private files, and stable errors without user data."""

import json
import os
from pathlib import Path
import stat

DATABASES = ("contact/contact.db", "message/message_0.db")


class ExportError(Exception):
    """Only fixed, developer-controlled error codes belong here."""


def canonical(path, *, directory=False):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ExportError("symlink_rejected")
    if path.resolve(strict=True) != path:
        raise ExportError("noncanonical_path")
    mode = path.stat().st_mode
    if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
        raise ExportError("not_regular_path")
    return path


def scoped_databases(root):
    root = canonical(root, directory=True)
    paths = {}
    for relative in DATABASES:
        path = canonical(root / relative)
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(str(path) + suffix)
            if sidecar.is_symlink():
                raise ExportError("sidecar_symlink_rejected")
            if sidecar.exists():
                canonical(sidecar)
        paths[relative] = path
    return paths


def private_json(path):
    path = canonical(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise ExportError("private_file_requires_owner_and_0600")
        if info.st_size > 1024 * 1024:
            raise ExportError("private_file_too_large")
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ExportError("json_object_required")
    return data


def private_text(path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    return os.fdopen(fd, "w", encoding="utf-8", newline="\n")


def new_output(path):
    path = Path(path).absolute()
    canonical(path.parent, directory=True)
    if path.is_symlink():
        raise ExportError("output_symlink_rejected")
    path.mkdir(mode=0o700)  # Existing outputs, even empty ones, must not be reused.
    os.chmod(path, 0o700)
    return path


def sql_text(value):
    # UTF-8 hex literal prevents SQL syntax from entering via names or identifiers.
    return "CAST(x'" + value.encode("utf-8").hex() + "' AS TEXT)"
