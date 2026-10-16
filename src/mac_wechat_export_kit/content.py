# SPDX-License-Identifier: MIT
# Adapted from the reviewed private export_selected_chat.py; see docs/SOURCES.md.
# Copyright (c) 2026 mac-wechat-export-kit contributors
"""Allowlisted readable text, explicit placeholders, bounded Zstandard decode."""

import re
import xml.etree.ElementTree as ET

MAX_TEXT = 10 * 1024 * 1024
LABELS = {1: "文字", 3: "图片", 34: "语音", 42: "名片", 43: "视频", 47: "表情",
          48: "位置", 49: "分享", 50: "通话", 10000: "系统消息"}


def unpack(raw):
    if len(raw) > MAX_TEXT:
        raise ValueError("content_limit")
    if raw.startswith(b"\x28\xb5\x2f\xfd"):
        try:
            import zstandard
        except ImportError:
            raise ValueError("zstandard_unavailable") from None
        try:
            size = zstandard.get_frame_parameters(raw).content_size
            if size not in (zstandard.CONTENTSIZE_UNKNOWN, zstandard.CONTENTSIZE_ERROR) and size > MAX_TEXT:
                raise ValueError("content_limit")
            raw = zstandard.ZstdDecompressor().decompress(
                raw, max_output_size=MAX_TEXT, allow_extra_data=False)
        except zstandard.ZstdError:
            raise ValueError("decode_error") from None
    if len(raw) > MAX_TEXT:
        raise ValueError("content_limit")
    return raw.decode("utf-8", "strict")


def parse_content(raw, number):
    base, subtype = number & 0xffffffff, number >> 32
    row = {"kind": LABELS.get(base, "其他消息"), "text": None, "content_status": "placeholder"}
    if base not in (1, 49, 10000):
        return row
    try:
        text = unpack(raw)
    except (UnicodeError, ValueError) as error:
        row["content_status"] = (str(error) if str(error) in
                                 {"content_limit", "zstandard_unavailable"} else "decode_error")
        return row
    if base == 1 or (base == 10000 and not text.lstrip().startswith("<")):
        row.update(text=text, content_status="text" if base == 1 else "system_text")
        return row
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, re.I):
        row["content_status"] = "structured_content_unparsed"
        return row
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        row["content_status"] = "structured_content_unparsed"
        return row
    if base == 10000:
        body = (root.findtext(".//revokemsg/replacemsg") or root.findtext(".//revokemsg/content")
                or root.findtext("content"))
        if body:
            row.update(text=body, content_status="system_text")
        else:
            row["content_status"] = "structured_content_unparsed"
        return row
    app = root if root.tag == "appmsg" else root.find(".//appmsg")
    if app is None:
        row["content_status"] = "structured_content_unparsed"
        return row
    row.update(text=app.findtext("title") or "", content_status="app_summary")
    description = app.findtext("des") or ""
    if description and description != row["text"]:
        row["description"] = description
    if subtype == 19:
        row["content_status"] = "forward_summary_not_expanded"
    if subtype == 57:
        quote = app.find("refermsg")
        if quote is not None:
            row["quote"] = {"sender_display_name": quote.findtext("displayname") or "",
                            "text": (quote.findtext("content") or "") if quote.findtext("type") == "1" else None}
    return row


def readable(row):
    body = row.get("text") or "[" + row["kind"] + "]"
    if row.get("description"):
        body += "\n" + row["description"]
    if row.get("quote"):
        quote = row["quote"]
        body += "\n> " + quote["sender_display_name"] + "：" + (quote["text"] if quote["text"] is not None else "[非文字引用未展开]")
    if row["content_status"] not in {"text", "system_text", "app_summary", "placeholder"}:
        body += " [" + row["content_status"] + "]"
    return body
