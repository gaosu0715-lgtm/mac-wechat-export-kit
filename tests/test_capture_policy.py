"""HMAC-authenticated fabricated pages, never process memory or real keys."""

import hashlib
import hmac
import unittest

from mac_wechat_export_kit.capture_policy import (GROUP, GROUP_KEY, IDENTITY_KEYS, candidate_keys,
                                                   intended_entitlements, verify_raw_key)
from mac_wechat_export_kit.safety import DATABASES, ExportError


def original_entitlements():
    original = {"com.apple.security.app-sandbox": True,
                "com.apple.security.cs.allow-jit": True, GROUP_KEY: GROUP[:],
                IDENTITY_KEYS[0]: GROUP[0], IDENTITY_KEYS[1]: "5A4RE8SF68"}
    original.update({"synthetic-existing-boolean-" + str(i): True for i in range(10)})
    return original


def synthetic_page(key, salt=b"S" * 16):
    page = bytearray(salt + b"C" * (4096 - 16))
    mac_key = hashlib.pbkdf2_hmac("sha512", key, bytes(x ^ 0x3a for x in salt), 2, 32)
    page[4032:] = hmac.new(mac_key, page[16:4032] + b"\x01\x00\x00\x00", hashlib.sha512).digest()
    return bytes(page)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.key = b"K" * 32
        self.pages = {name: synthetic_page(self.key) for name in DATABASES}

    def test_exact_fifteen_delta_preserves_groups_and_sandbox(self):
        original = original_entitlements()
        result = intended_entitlements(original)
        self.assertEqual(len(result), 15)
        self.assertEqual(result[GROUP_KEY], GROUP)
        self.assertTrue(result["com.apple.security.app-sandbox"])
        self.assertTrue(result["com.apple.security.cs.allow-jit"])
        self.assertFalse(set(IDENTITY_KEYS) & set(result))
        self.assertEqual(set(result) - set(original), {"com.apple.security.get-task-allow", "com.apple.security.cs.disable-library-validation"})
        self.assertNotIn("com.apple.security.cs.allow-unsigned-executable-memory", result)

    def test_changed_group_or_identity_fails_closed(self):
        for key, value in ((GROUP_KEY, ["other"]), (IDENTITY_KEYS[1], "other"),
                           ("com.apple.security.app-sandbox", False)):
            with self.subTest(key=key):
                original = original_entitlements()
                original[key] = value
                with self.assertRaises(ExportError):
                    intended_entitlements(original)

    def test_raw_key_path_no_second_password_derivation(self):
        reads = []
        def memory(address, size):
            reads.append((address, size))
            return bytes(x ^ 0x3a for x in b"S" * 16) if address == 20 else self.key
        found = candidate_keys([2, 10, 32, 20, 16, 5, 2], self.pages, memory, lambda: None)
        self.assertEqual(found, {name: self.key for name in DATABASES})
        self.assertEqual(reads, [(20, 16), (10, 32)])

    def test_password_path_derives_once_for_matching_salt(self):
        secret, salt = b"synthetic-passphrase", b"S" * 16
        key = hashlib.pbkdf2_hmac("sha512", secret, salt, 256000, 32)
        pages = {name: synthetic_page(key) for name in DATABASES}
        found = candidate_keys([2, 10, len(secret), 20, 16, 5, 256000], pages,
                               lambda address, size: salt if address == 20 else secret, lambda: None)
        self.assertEqual(found[DATABASES[0]], key)

    def test_unmatched_salt_never_reads_secret(self):
        reads = []
        def memory(address, size):
            reads.append(address)
            return b"X" * 16
        self.assertEqual(candidate_keys([2, 10, 32, 20, 16, 5, 2], self.pages, memory, lambda: None), {})
        self.assertEqual(reads, [20])

    def test_invalid_shapes_never_read(self):
        for args in ([1, 10, 32, 20, 16, 5, 2], [2, 10, 33, 20, 16, 5, 2], [2, 10, 257, 20, 16, 5, 256000]):
            with self.subTest(args=args):
                def memory(*args):
                    self.fail("unexpected memory access")
                self.assertEqual(candidate_keys(args, self.pages, memory, lambda: None), {})

    def test_deadline_between_salt_and_secret_blocks_secret(self):
        checks, reads = [], []
        def check():
            checks.append(True)
            if len(checks) == 2:
                raise ExportError("capture_deadline")
        def memory(address, size):
            reads.append(address)
            return bytes(x ^ 0x3a for x in b"S" * 16)
        with self.assertRaisesRegex(ExportError, "capture_deadline"):
            candidate_keys([2, 10, 32, 20, 16, 5, 2], self.pages, memory, check)
        self.assertEqual(reads, [20])

    def test_damaged_page_or_wrong_key_rejected(self):
        page = bytearray(self.pages[DATABASES[0]])
        page[100] ^= 1
        self.assertFalse(verify_raw_key(self.key, page))
        self.assertFalse(verify_raw_key(b"W" * 32, self.pages[DATABASES[0]]))
