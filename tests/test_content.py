import importlib.util
import json
import sys
import unittest
from unittest.mock import patch

from mac_wechat_export_kit.content import MAX_TEXT, parse_content, unpack


class ContentTests(unittest.TestCase):
    def test_unicode_and_nul_preserved(self):
        body = "中文🙂\n\x00"
        self.assertEqual(parse_content(body.encode(), 1)["text"], body)

    def test_invalid_utf8_explicit(self):
        self.assertEqual(parse_content(b"\xff", 1)["content_status"], "decode_error")

    def test_oversize_bounded(self):
        self.assertEqual(parse_content(b"x" * (MAX_TEXT + 1), 1)["content_status"], "content_limit")

    def test_media_never_decoded(self):
        row = parse_content(b"TOKEN_SENTINEL", 3)
        self.assertEqual(row["content_status"], "placeholder")
        self.assertNotIn("TOKEN", json.dumps(row))

    def test_share_allowlist(self):
        row = parse_content(b"<msg><appmsg><title>visible</title><des>description</des><aeskey>TOKEN</aeskey><url>URL_SENTINEL</url></appmsg></msg>", 49)
        self.assertEqual(row["text"], "visible")
        self.assertEqual(row["description"], "description")
        self.assertNotIn("TOKEN", json.dumps(row))
        self.assertNotIn("URL_SENTINEL", json.dumps(row))

    def test_entity_rejected(self):
        row = parse_content(b'<!DOCTYPE msg [<!ENTITY x "TOKEN">]><msg><appmsg><title>&x;</title></appmsg></msg>', 49)
        self.assertEqual(row["content_status"], "structured_content_unparsed")

    def test_broken_xml_explicit(self):
        self.assertEqual(parse_content(b"<msg>", 49)["content_status"], "structured_content_unparsed")

    def test_system_variants(self):
        for text in ("plain", "<sysmsg><content>plain</content></sysmsg>",
                     "<sysmsg><revokemsg><replacemsg>plain</replacemsg></revokemsg></sysmsg>",
                     "<sysmsg><revokemsg><content>plain</content></revokemsg></sysmsg>"):
            with self.subTest(text=text):
                self.assertEqual(parse_content(text.encode(), 10000)["text"], "plain")

    def test_nontext_quote_not_expanded(self):
        row = parse_content(b"<appmsg><title>reply</title><refermsg><type>3</type><content>TOKEN</content></refermsg></appmsg>", (57 << 32) | 49)
        self.assertIsNone(row["quote"]["text"])
        self.assertNotIn("TOKEN", json.dumps(row))

    def test_forward_status_is_honest(self):
        row = parse_content(b"<appmsg><title>summary</title><recorditem>TOKEN</recorditem></appmsg>", (19 << 32) | 49)
        self.assertEqual(row["content_status"], "forward_summary_not_expanded")
        self.assertNotIn("TOKEN", json.dumps(row))

    def test_missing_zstandard_is_explicit(self):
        with patch.dict(sys.modules, {"zstandard": None}):
            self.assertEqual(parse_content(b"\x28\xb5\x2f\xfdtoy", 1)["content_status"], "zstandard_unavailable")

    @unittest.skipUnless(importlib.util.find_spec("zstandard"), "optional zstandard not installed")
    def test_real_zstandard_bounds_and_roundtrip(self):
        import zstandard
        body = "压缩合成🙂".encode()
        compressed = zstandard.ZstdCompressor().compress(body)
        self.assertEqual(unpack(compressed), body.decode())
        with self.assertRaises(ValueError):
            unpack(zstandard.ZstdCompressor().compress(b"x" * (MAX_TEXT + 1)))
