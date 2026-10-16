# SPDX-License-Identifier: MIT
# Content/rendering flow adapted from reviewed private export_selected_chat.py.
# Copyright (c) 2026 mac-wechat-export-kit contributors
"""Export one fixed shard and one explicitly bound one-to-one conversation."""

from collections import Counter
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from .content import MAX_TEXT, parse_content, readable
from .safety import ExportError, canonical, new_output, private_text, sql_text

SCOPE_NOTE = "仅指定 message_0.db 的单个一对一会话；未验证其他分库或完整历史。"
MEDIA_NOTE = "不读取媒体附件；分享只保留可读摘要，合并转发与非文字引用未展开。"


def page_head(title):
    return ("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; "
            "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">"
            "<title>" + html.escape(title) + "</title><style>"
            "body{font:16px/1.6 system-ui;max-width:960px;margin:30px auto;padding:0 20px}"
            "article{border:1px solid #ccc;padding:12px;margin:12px 0}"
            "pre{font:inherit;white-space:pre-wrap;overflow-wrap:anywhere}"
            "header{color:#555;font-size:13px}</style></head><body>")


def write_page(folder, number, rows):
    name = "page-{:05d}.html".format(number)
    with private_text(folder / name) as stream:
        stream.write(page_head("指定会话 · 第{}页".format(number)))
        stream.write('<nav><a href="index.html">目录</a></nav>')
        for row in rows:
            stream.write('<article data-local-id="{}"><header>'.format(row["local_id"]))
            stream.write(html.escape(row["created_at"] + " · " + row["sender_label"] + " · " + row["kind"]))
            stream.write("</header><pre>" + html.escape(readable(row)) + "</pre></article>")
        stream.write("</body></html>")
    return name


def export_conversation(opener, *, contact_name, expected_username, self_username,
                        output, timezone="UTC", page_size=1000):
    """opener(relative) returns a context manager exposing query(sql).

    Production opener is always CipherDB in read-only mode. Tests inject a toy
    SQLite adapter; the public CLI never accepts plaintext source databases.
    """
    if not 1 <= page_size <= 2000:
        raise ExportError("invalid_page_size")
    if (not contact_name or not expected_username or not self_username
            or expected_username == self_username or expected_username.endswith("@chatroom")):
        raise ExportError("invalid_one_to_one_binding")
    zone = ZoneInfo(timezone)
    with opener("contact/contact.db") as contacts:
        matches = contacts.query("SELECT username FROM contact WHERE nick_name=" + sql_text(contact_name)
                                 + " OR remark=" + sql_text(contact_name))
        if len(matches) != 1 or matches[0]["username"] != expected_username:
            raise ExportError("contact_missing_ambiguous_or_binding_changed")
    # Identifiers are constructed only from a digest, never interpolated user SQL.
    table = '"Msg_' + hashlib.md5(expected_username.encode("utf-8")).hexdigest() + '"'
    pages, seen, statuses = [], set(), Counter()
    previous_order = None
    output = new_output(output)
    folder = output / "HTML"
    folder.mkdir(mode=0o700)
    with opener("message/message_0.db") as database:
        database.query("PRAGMA temp_store=MEMORY")
        database.query("BEGIN")
        source_count = int(database.query("SELECT count(*) AS n FROM " + table)[0]["n"])
        participants = database.query("SELECT DISTINCT m.real_sender_id,n.user_name FROM " + table
                                      + " m LEFT JOIN Name2Id n ON n.rowid=m.real_sender_id")
        identities = {}
        for participant in participants:
            name = participant["user_name"]
            if name not in (None, self_username, expected_username):
                raise ExportError("unexpected_conversation_participant")
            identities[participant["real_sender_id"]] = (
                "self" if name == self_username else "contact" if name == expected_username else "unknown")
        metadata = {"schema_version": 1, "timezone": timezone, "source_message_database": "message/message_0.db",
                    "snapshot_message_count": source_count, "scope_note": SCOPE_NOTE, "media_note": MEDIA_NOTE,
                    "full_history_verified": False, "media_files_read": False}
        with private_text(output / "messages.json") as structured, private_text(output / "messages.txt") as plain:
            structured.write('{"metadata":' + json.dumps(metadata, ensure_ascii=False) + ',"messages":[\n')
            plain.write("指定会话导出\n" + SCOPE_NOTE + "\n" + MEDIA_NOTE + "\n\n")
            offset = 0
            while offset < source_count:
                rows = database.query(
                    "SELECT local_id,server_id,local_type,create_time,real_sender_id,"
                    "CASE WHEN (local_type & 4294967295) IN (1,49,10000) THEN "
                    "hex(substr(CASE WHEN message_content IS NULL OR length(message_content)=0 "
                    "THEN compress_content ELSE message_content END,1," + str(MAX_TEXT + 1) + ")) ELSE NULL END AS body "
                    "FROM " + table + " ORDER BY create_time,local_id LIMIT " + str(page_size) + " OFFSET " + str(offset))
                if not rows:
                    raise ExportError("snapshot_count_mismatch")
                rendered = []
                for source in rows:
                    identifier, stamp, number = (int(source[name]) for name in ("local_id", "create_time", "local_type"))
                    if identifier in seen:
                        raise ExportError("duplicate_local_id")
                    seen.add(identifier)
                    order = (stamp, identifier)
                    if previous_order is not None and order < previous_order:
                        raise ExportError("chronology_mismatch")
                    previous_order = order
                    sender = identities.get(source["real_sender_id"], "unknown")
                    if sender == "unknown":
                        if number & 0xffffffff != 10000:
                            raise ExportError("non_system_sender_unresolved")
                        sender = "system"
                    row = {"local_id": identifier, "server_id": source["server_id"], "timestamp": stamp,
                           "created_at": datetime.fromtimestamp(stamp, zone).isoformat(), "sender": sender,
                           "sender_label": {"self": "我", "contact": "对方", "system": "系统"}[sender],
                           "local_type": str(number)}
                    row.update(parse_content(bytes.fromhex(source["body"] or ""), number))
                    statuses[row["content_status"]] += 1
                    if offset + len(rendered):
                        structured.write(",\n")
                    structured.write(json.dumps(row, ensure_ascii=False))
                    plain.write(row["created_at"] + " " + row["sender_label"] + "\n" + readable(row) + "\n\n")
                    rendered.append(row)
                pages.append(write_page(folder, len(pages) + 1, rendered))
                offset += len(rows)
            structured.write("\n]}\n")
        database.query("ROLLBACK")
    if len(seen) != source_count:
        raise ExportError("export_count_mismatch")
    with private_text(folder / "index.html") as stream:
        stream.write(page_head("指定会话导出") + "<h1>指定会话导出</h1><p>" + SCOPE_NOTE + "</p><p>" + MEDIA_NOTE + "</p>")
        stream.write('<p><a href="../messages.txt">TXT</a> · <a href="../messages.json">JSON</a></p><ol>')
        for number, page in enumerate(pages, 1):
            stream.write('<li><a href="' + page + '">第' + str(number) + "页</a></li>")
        stream.write("</ol></body></html>")
    data = json.loads((output / "messages.json").read_text(encoding="utf-8"))
    if len(data["messages"]) != source_count:
        raise ExportError("serialized_count_mismatch")
    summary = {"message_count": source_count, "html_pages": len(pages), "source_read_only": True,
               "full_history_verified": False, "media_files_read": False,
               "content_status_counts": dict(statuses)}
    names = ["messages.json", "messages.txt", "HTML/index.html"] + ["HTML/" + name for name in pages]
    digests = {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in names}
    # This marker is written last. An interrupted directory without it is incomplete.
    with private_text(output / "manifest.json") as stream:
        json.dump({"schema_version": 1, "complete": True, "summary": summary, "sha256": digests},
                  stream, ensure_ascii=False, indent=2)
    verify_output(output)
    return summary


def verify_output(output):
    """Local artifact consistency only; this cannot prove source history completeness."""
    output = canonical(output, directory=True)
    manifest_path = canonical(output / "manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("complete") is not True:
        raise ExportError("incomplete_export")
    hashes = manifest.get("sha256")
    if not isinstance(hashes, dict):
        raise ExportError("invalid_manifest")
    count, page_count = manifest["summary"]["message_count"], manifest["summary"]["html_pages"]
    if type(count) is not int or type(page_count) is not int or not 0 <= page_count <= count:
        raise ExportError("invalid_manifest_counts")
    expected = {"messages.json", "messages.txt", "HTML/index.html"}
    expected.update("HTML/page-{:05d}.html".format(i) for i in range(1, page_count + 1))
    if set(hashes) != expected:
        raise ExportError("manifest_file_scope_mismatch")
    articles = 0
    for name, digest in hashes.items():
        path = canonical(output / name)
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ExportError("invalid_manifest_digest")
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != digest:
            raise ExportError("output_digest_mismatch")
        if name.startswith("HTML/page-"):
            articles += body.count(b"<article ")
    data = json.loads((output / "messages.json").read_text(encoding="utf-8"))
    rows = data["messages"]
    if len(rows) != count or articles != count or data["metadata"]["snapshot_message_count"] != count:
        raise ExportError("output_count_mismatch")
    identifiers = [row["local_id"] for row in rows]
    orders = [(row["timestamp"], row["local_id"]) for row in rows]
    if len(set(identifiers)) != count or orders != sorted(orders):
        raise ExportError("output_identity_or_order_mismatch")
    return {"verified": True, "message_count": count, "files_checked": len(hashes)}
