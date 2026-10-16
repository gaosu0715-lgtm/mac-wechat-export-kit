# SPDX-License-Identifier: MIT
# Portions derived from acmerfight's sqlcipher_probe.py, pinned revision in NOTICE.
# Copyright (c) 2026 Contributors
"""Small SQLCipher C API adapter. No automatic library search or key capture."""

import ctypes as C
import hashlib
import os
from pathlib import Path
import re

from .safety import DATABASES, ExportError, canonical, private_json


def load_library(path, expected_sha256):
    path = canonical(path)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ExportError("library_digest_required")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ExportError("library_digest_mismatch")
    lib = C.CDLL(str(path))
    signatures = {
        "sqlite3_open_v2": ([C.c_char_p, C.POINTER(C.c_void_p), C.c_int, C.c_char_p], C.c_int),
        "sqlite3_close": ([C.c_void_p], C.c_int),
        "sqlite3_key": ([C.c_void_p, C.c_void_p, C.c_int], C.c_int),
        "sqlite3_exec": ([C.c_void_p, C.c_char_p, C.c_void_p, C.c_void_p, C.c_void_p], C.c_int),
        "sqlite3_busy_timeout": ([C.c_void_p, C.c_int], C.c_int),
        "sqlite3_db_readonly": ([C.c_void_p, C.c_char_p], C.c_int),
    }
    try:
        for name, (arguments, returns) in signatures.items():
            function = getattr(lib, name)
            function.argtypes, function.restype = arguments, returns
    except AttributeError:
        raise ExportError("sqlcipher_api_missing") from None
    return lib


def load_keys(path):
    data = private_json(path)
    entries = data.get("keys")
    if not isinstance(entries, dict) or set(entries) != set(DATABASES):
        raise ExportError("key_scope_requires_exact_two_databases")
    keys = {}
    for name, entry in entries.items():
        key = entry.get("enc_key") if isinstance(entry, dict) else None
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", key):
            raise ExportError("raw_key_requires_64_hex")
        keys[name] = key.lower()
    return keys


class CipherDB:
    def __init__(self, lib, path, key, *, fixture_write=False):
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", key):
            raise ExportError("raw_key_requires_64_hex")
        self.lib, self.ptr = lib, C.c_void_p()
        flags = 6 if fixture_write else 1  # READWRITE|CREATE only for synthetic tests.
        rc = lib.sqlite3_open_v2(os.fsencode(path), C.byref(self.ptr), flags, None)
        if rc:
            self.close()
            raise ExportError("cipher_open_failed")
        try:
            self.query("PRAGMA cipher_log_level=NONE")
            raw_literal = ("x'" + key + "'").encode("ascii")
            if lib.sqlite3_key(self.ptr, raw_literal, len(raw_literal)):
                raise ExportError("cipher_key_setup_failed")
            self.query("PRAGMA cipher_compatibility=4")
            version = self.query("PRAGMA cipher_version")
            if not version or not next(iter(version[0].values())).startswith("4."):
                raise ExportError("sqlcipher_4_required")
            lib.sqlite3_busy_timeout(self.ptr, 2000)
            if not fixture_write:
                self.query("PRAGMA query_only=ON")
                if (lib.sqlite3_db_readonly(self.ptr, b"main") != 1
                        or self.query("PRAGMA query_only")[0]["query_only"] != "1"):
                    raise ExportError("source_not_read_only")
            self.query("SELECT count(*) FROM sqlite_master")
        except BaseException:
            self.close()
            raise

    def query(self, sql):
        rows = []
        failure = []
        callback_type = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_int,
                                   C.POINTER(C.c_char_p), C.POINTER(C.c_char_p))

        def collect(_, count, values, names):
            try:
                rows.append({names[i].decode("utf-8"): values[i].decode("utf-8")
                             if values[i] is not None else None for i in range(count)})
                return 0
            except Exception:
                failure.append(True)
                return 1

        callback = callback_type(collect)
        rc = self.lib.sqlite3_exec(self.ptr, sql.encode("utf-8"), callback, None, None)
        if rc or failure:
            # Never include SQL, paths, native diagnostics, or key material.
            raise ExportError("cipher_query_failed")
        return rows

    def close(self):
        if self.ptr:
            self.lib.sqlite3_close(self.ptr)
            self.ptr = C.c_void_p()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
