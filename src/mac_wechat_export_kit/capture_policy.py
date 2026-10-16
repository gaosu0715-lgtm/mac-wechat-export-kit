# SPDX-License-Identifier: MIT
# Derived from pinned upstream capture_keys.py and reviewed capture15_policy.py.
# Copyright (c) 2026 Contributors
# Copyright (c) 2026 mac-wechat-export-kit contributors
"""Pure bounded candidate verification. No debugger, filesystem, or UI access."""

import hashlib
import hmac

from .safety import DATABASES, ExportError

GROUP_KEY = "com.apple.security.application-groups"
GROUP = ["5A4RE8SF68.com.tencent.xinWeChat"]
IDENTITY_KEYS = ("com.apple.application-identifier", "com.apple.developer.team-identifier")


def intended_entitlements(original):
    if (len(original) != 15 or original.get(GROUP_KEY) != GROUP
            or original.get(IDENTITY_KEYS[0]) != GROUP[0]
            or original.get(IDENTITY_KEYS[1]) != "5A4RE8SF68"
            or original.get("com.apple.security.app-sandbox") is not True
            or "com.apple.security.cs.allow-unsigned-executable-memory" in original
            or "com.apple.security.get-task-allow" in original
            or "com.apple.security.cs.disable-library-validation" in original):
        raise ExportError("unsupported_original_entitlements")
    result = dict(original)
    for name in IDENTITY_KEYS:
        result.pop(name)
    result["com.apple.security.get-task-allow"] = True
    result["com.apple.security.cs.disable-library-validation"] = True
    if len(result) != 15 or result[GROUP_KEY] != GROUP:
        raise ExportError("entitlement_scope_changed")
    return result


def validate_pages(pages):
    if set(pages) != set(DATABASES) or any(len(p) != 4096 or p.startswith(b"SQLite format 3\0") for p in pages.values()):
        raise ExportError("unsupported_encrypted_pages")


def verify_raw_key(key, page):
    if len(key) != 32 or len(page) != 4096:
        return False
    mac_key = hashlib.pbkdf2_hmac("sha512", key, bytes(x ^ 0x3a for x in page[:16]), 2, 32)
    actual = hmac.new(mac_key, page[16:4032] + b"\x01\x00\x00\x00", hashlib.sha512).digest()
    return hmac.compare_digest(actual, page[4032:])


def candidate_keys(arguments, pages, read_memory, check):
    """Called only at an owned, identity-verified stopped breakpoint.

    check() enforces the single original deadline/cancellation/resource budget.
    A mismatching salt never permits a password/raw-key parameter read.
    """
    validate_pages(pages)
    check()
    if len(arguments) != 7:
        raise ExportError("invalid_argument_shape")
    algorithm, pointer, length, salt_pointer, salt_length, prf, rounds = arguments
    if (algorithm != 2 or salt_length != 16 or prf != 5 or rounds not in (2, 256000)
            or not 0 < length <= 256 or rounds == 2 and length != 32):
        return {}
    salt_argument = read_memory(salt_pointer, 16)
    check()
    salt = salt_argument if rounds == 256000 else bytes(x ^ 0x3a for x in salt_argument)
    matches = {name: page for name, page in pages.items() if page[:16] == salt}
    if len(salt) != 16 or not matches:
        return {}
    secret = read_memory(pointer, length)
    check()
    if len(secret) != length:
        raise ExportError("short_secret_parameter")
    key = hashlib.pbkdf2_hmac("sha512", secret, salt, 256000, 32) if rounds == 256000 else secret
    check()
    return {name: key for name, page in matches.items() if verify_raw_key(key, page)}
