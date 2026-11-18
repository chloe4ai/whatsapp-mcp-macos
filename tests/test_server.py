"""Tests against a synthetic ChatStorage.sqlite (no real WhatsApp data needed).

Run: uv run --with pytest pytest
"""

import sqlite3
import time

import pytest

APPLE_EPOCH = 978307200


def apple(ts: float) -> float:
    return ts - APPLE_EPOCH


@pytest.fixture()
def wa(tmp_path, monkeypatch):
    path = tmp_path / "ChatStorage.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE ZWACHATSESSION (Z_PK INTEGER PRIMARY KEY, ZCONTACTJID TEXT, ZPARTNERNAME TEXT,
            ZLASTMESSAGEDATE REAL, ZUNREADCOUNT INTEGER, ZSESSIONTYPE INTEGER, ZARCHIVED INTEGER,
            ZREMOVED INTEGER);
        CREATE TABLE ZWAMESSAGE (Z_PK INTEGER PRIMARY KEY, ZCHATSESSION INTEGER, ZISFROMME INTEGER,
            ZMESSAGEDATE REAL, ZTEXT TEXT, ZFROMJID TEXT, ZTOJID TEXT, ZMESSAGETYPE INTEGER,
            ZGROUPMEMBER INTEGER, ZPUSHNAME TEXT, ZSTARRED INTEGER);
        CREATE TABLE ZWAGROUPMEMBER (Z_PK INTEGER PRIMARY KEY, ZCHATSESSION INTEGER,
            ZMEMBERJID TEXT, ZCONTACTNAME TEXT, ZFIRSTNAME TEXT);
        CREATE TABLE ZWAPROFILEPUSHNAME (Z_PK INTEGER PRIMARY KEY, ZJID TEXT, ZPUSHNAME TEXT);
        CREATE TABLE ZWAMEDIAITEM (Z_PK INTEGER PRIMARY KEY, ZMESSAGE INTEGER, ZTITLE TEXT,
            ZVCARDNAME TEXT, ZLATITUDE REAL, ZLONGITUDE REAL, ZMOVIEDURATION REAL);
        """
    )
    now = time.time()
    conn.executemany(
        "INSERT INTO ZWACHATSESSION VALUES (?,?,?,?,?,?,?,?)",
        [
            (1, "14155550101@s.whatsapp.net", "Mom", apple(now - 60), 1, 0, 0, 0),
            (2, "120363000000000001@g.us", "Mom & Dad", apple(now - 3600), 0, 1, 0, 0),
            (3, "14155550102@s.whatsapp.net", "Old Friend", apple(now - 9e6), 0, 0, 1, 0),
            (4, "status@broadcast", None, apple(now), 0, 3, 0, 0),
            (5, "99887766554433@lid", "Hidden Number", apple(now - 7200), 0, 0, 0, 0),
        ],
    )
    conn.executemany(
        "INSERT INTO ZWAGROUPMEMBER VALUES (?,?,?,?,?)",
        [(1, 2, "14155550103@s.whatsapp.net", None, None)],
    )
    conn.execute("INSERT INTO ZWAPROFILEPUSHNAME VALUES (1, '14155550103@s.whatsapp.net', 'Dad ~')")
    conn.executemany(
        "INSERT INTO ZWAMESSAGE VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (1, 1, 0, apple(now - 7200), "Dinner on Sunday?", "14155550101@s.whatsapp.net", None, 0, None, "Mommy", 0),
            (2, 1, 1, apple(now - 7000), "Yes! 100% in", None, "14155550101@s.whatsapp.net", 0, None, None, 0),
            (3, 1, 0, apple(now - 60), None, "14155550101@s.whatsapp.net", None, 1, None, "Mommy", 0),
            (4, 2, 0, apple(now - 3600), "Sunday dinner at 6", "120363000000000001@g.us", None, 0, 1, "Dad ~", 1),
            (5, 3, 0, apple(now - 9e6), "long time no see", "14155550102@s.whatsapp.net", None, 0, None, None, 0),
            (6, 2, 0, apple(now - 3500), None, "120363000000000001@g.us", None, 6, None, None, 0),
        ],
    )
    conn.execute("INSERT INTO ZWAMEDIAITEM VALUES (1, 3, 'the menu', NULL, NULL, NULL, NULL)")
    conn.commit()
    conn.close()

    monkeypatch.setenv("WHATSAPP_DB_DIR", str(tmp_path))
    from whatsapp_mcp_macos import server

    monkeypatch.setattr(server, "STATE_FILE", tmp_path / "state.json")
    return server


def test_status(wa):
    status = wa.get_status()
    assert status["ok"] and status["chats"] == 5 and status["messages"] == 6


def test_status_reports_missing_db(wa, monkeypatch, tmp_path):
    monkeypatch.setenv("WHATSAPP_DB_DIR", str(tmp_path / "nope"))
    status = wa.get_status()
    assert status["ok"] is False and "not found" in status["problem"]


def test_list_chats_order_and_filters(wa):
    chats = wa.list_chats()
    assert [c["name"] for c in chats] == ["Mom", "Mom & Dad", "Hidden Number"]  # no status, no archived
    assert chats[0]["phone"] == "+14155550101" and chats[0]["unread"] == 1
    assert "Old Friend" in [c["name"] for c in wa.list_chats(include_archived=True)]
    assert [c["name"] for c in wa.list_groups()] == ["Mom & Dad"]


def test_read_messages_exact_name_beats_partial(wa):
    result = wa.read_messages("mom")
    assert result["chat"]["name"] == "Mom"
    msgs = result["messages"]
    assert [m["from"] for m in msgs] == ["Mom", "me", "Mom"]
    assert msgs[0]["text"] == "Dinner on Sunday?"
    assert msgs[2]["text"] == "[image] the menu"


def test_read_messages_by_phone_and_group_sender(wa):
    assert wa.read_messages("+1 (415) 555-0101", limit=1)["messages"][0]["text"] == "[image] the menu"
    group = wa.read_messages("Mom & Dad")["messages"]
    assert group[0]["from"] == "Dad ~" and group[0]["starred"] is True


def test_ambiguous_and_unknown_chat(wa):
    with pytest.raises(wa.WhatsAppDBError, match="matches 2 chats"):
        wa.read_messages("mo")  # "Mom" and "Mom & Dad", neither an exact match
    with pytest.raises(wa.WhatsAppDBError, match="No chat matches"):
        wa.read_messages("Nobody")


def test_search_escapes_wildcards(wa):
    hits = wa.search("sunday")
    assert {h["chat"] for h in hits} == {"Mom", "Mom & Dad"}
    assert [h["text"] for h in wa.search("100%")] == ["Yes! 100% in"]
    assert wa.search("%") == [wa.search("100%")[0]]
    assert wa.search("sunday", chat="Mom & Dad")[0]["from"] == "Dad ~"


def test_date_window(wa):
    assert wa.read_messages("Old Friend", since="2001-01-02")["messages"]
    assert wa.read_messages("Old Friend", until="2001-01-02")["messages"] == []


def test_check_new_checkpoint(wa):
    first = wa.check_new()
    assert first["new_message_count"] == 3  # incoming, last 24h, system message skipped
    assert {c["chat"] for c in first["chats"]} == {"Mom", "Mom & Dad"}
    assert wa.check_new()["new_message_count"] == 0


def test_send_refuses_groups_and_lids(wa, monkeypatch):
    calls = []
    monkeypatch.setattr(wa, "_run", lambda cmd: calls.append(cmd))
    with pytest.raises(wa.WhatsAppDBError, match="only send to individual"):
        wa.send("Mom & Dad", "hi")
    with pytest.raises(wa.WhatsAppDBError, match="no phone number"):
        wa.send("Hidden Number", "hi")
    assert calls == []


def test_send_drafts_by_default(wa, monkeypatch):
    calls = []

    class Done:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(wa, "_run", lambda cmd: calls.append(cmd) or Done())
    result = wa.send("Mom", "See you at 6 & bring wine?")
    assert result["status"] == "drafted" and result["to"] == "Mom"
    assert calls == [["open", "whatsapp://send?phone=14155550101&text=See%20you%20at%206%20%26%20bring%20wine%3F"]]
