"""Fabricated identities, content and keys only. Never discovers user data."""

import hashlib
import json
from pathlib import Path
import sqlite3

from mac_wechat_export_kit.safety import DATABASES, private_text, sql_text

CONTACT = "合成联系人"
USERNAME = "contact_fixture"
SELF = "self_fixture"
TABLE = "Msg_" + hashlib.md5(USERNAME.encode()).hexdigest()
FAKE_KEYS = {DATABASES[0]: "11" * 32, DATABASES[1]: "22" * 32}
RAW_ROWS = [
    (2, 1, 2, b"<script>synthetic</script>\xe4\xb8\xad\xe6\x96\x87"),
    (1, 1, 1, "合成🙂\nfirst".encode()),
    (3, (57 << 32) | 49, 2, b"<msg><appmsg><title>reply</title><refermsg><type>1</type><displayname>fixture</displayname><content>quote</content></refermsg><aeskey>MEDIA_TOKEN_SENTINEL</aeskey><url>https://example.invalid/token</url></appmsg></msg>"),
    (4, 3, 2, b"MEDIA_TOKEN_SENTINEL"),
    (5, 10000, 99, b"<sysmsg><content>synthetic notice</content></sysmsg>"),
    (6, (19 << 32) | 49, 2, b"<msg><appmsg><title>forward summary</title><recorditem>FORWARD_PAYLOAD_SENTINEL</recorditem></appmsg></msg>"),
]


class PlainFixtureDB:
    """Test/demo-only adapter, explicitly readonly. Not a public export backend."""

    def __init__(self, path):
        self.connection = sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)
        self.connection.execute("PRAGMA query_only=ON")

    def query(self, sql):
        cursor = self.connection.execute(sql)
        return [{item[0]: str(value) if value is not None else None
                 for item, value in zip(cursor.description, row)} for row in cursor.fetchall()]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.connection.close()


def make_fixtures(root, writer=None, rows=None):
    root = Path(root)
    (root / "contact").mkdir(parents=True)
    (root / "message").mkdir()
    if writer is None:
        class Writer:
            def __init__(self, path):
                self.connection = sqlite3.connect(path)
            def query(self, sql):
                self.connection.executescript(sql)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.connection.commit()
                self.connection.close()
        writer = lambda relative: Writer(root / relative)
    with writer(DATABASES[0]) as database:
        database.query("CREATE TABLE contact(username TEXT,nick_name TEXT,remark TEXT);")
        database.query("INSERT INTO contact VALUES(" + sql_text(USERNAME) + "," + sql_text(CONTACT) + ",'');")
        database.query("INSERT INTO contact VALUES('unrelated_fixture','unrelated','');")
    with writer(DATABASES[1]) as database:
        database.query("CREATE TABLE Name2Id(user_name TEXT);")
        database.query("INSERT INTO Name2Id(rowid,user_name) VALUES(1,'self_fixture'),(2,'contact_fixture');")
        database.query('CREATE TABLE "' + TABLE + '" (local_id INTEGER,server_id INTEGER,local_type INTEGER,'
                       'create_time INTEGER,real_sender_id INTEGER,message_content BLOB,compress_content BLOB);')
        for identifier, kind, sender, body in (RAW_ROWS if rows is None else rows):
            database.query('INSERT INTO "' + TABLE + '" VALUES(' + ",".join(map(str, (identifier, identifier, kind,
                           1700000000 + (identifier // 2), sender))) + ",x'" + body.hex() + "',NULL);")
        database.query("CREATE TABLE unrelated_chat(body TEXT); INSERT INTO unrelated_chat VALUES('OTHER_CHAT_SENTINEL');")
    # A poison file demonstrates the fixed path workflow never scans other shards.
    (root / "message/message_1.db").write_bytes(b"UNAPPROVED_SHARD_SENTINEL")
    return root


def save_keys(path):
    with private_text(path) as stream:
        json.dump({"keys": {name: {"enc_key": value} for name, value in FAKE_KEYS.items()}}, stream)
