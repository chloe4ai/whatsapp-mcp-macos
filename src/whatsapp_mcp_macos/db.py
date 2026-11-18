"""Read-only access to WhatsApp Desktop's local ChatStorage.sqlite on macOS.

The macOS app (Mac Catalyst build) keeps the same Core Data store as the
iOS app, unencrypted, in its shared group container. We only ever open it
read-only; WhatsApp itself stays the single writer.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Core Data timestamps count seconds from 2001-01-01 UTC.
APPLE_EPOCH = 978307200

DEFAULT_DIR = Path.home() / "Library/Group Containers/group.net.whatsapp.WhatsApp.shared"

SESSION_TYPES = {0: "private", 1: "group", 2: "broadcast", 3: "status"}

MESSAGE_TYPES = {
    0: "text",
    1: "image",
    2: "video",
    3: "voice",
    4: "contact",
    5: "location",
    6: "system",
    7: "link",
    8: "document",
    10: "system",
    11: "gif",
    14: "deleted",
    15: "sticker",
    46: "poll",
}


class WhatsAppDBError(RuntimeError):
    """Raised with a message that is safe and useful to show to the user."""


def db_dir() -> Path:
    return Path(os.environ.get("WHATSAPP_DB_DIR") or DEFAULT_DIR)


def db_path() -> Path:
    return db_dir() / "ChatStorage.sqlite"


def to_iso(apple_ts) -> str | None:
    if apple_ts is None:
        return None
    return (
        datetime.fromtimestamp(float(apple_ts) + APPLE_EPOCH, tz=timezone.utc)
        .astimezone()
        .strftime("%Y-%m-%d %H:%M:%S")
    )


def from_iso(text: str) -> float:
    """Parse 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM[:SS]' (local time) to Apple epoch."""
    text = text.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).astimezone().timestamp() - APPLE_EPOCH
        except ValueError:
            continue
    raise WhatsAppDBError(f"Can't parse date {text!r}; use YYYY-MM-DD or YYYY-MM-DD HH:MM.")


def connect() -> sqlite3.Connection:
    path = db_path()
    try:
        exists = path.exists()
    except PermissionError:
        exists = True  # falls through to the open, which reports the TCC problem
    if not exists:
        raise WhatsAppDBError(
            f"WhatsApp database not found at {path}. Install WhatsApp Desktop from the "
            "Mac App Store, link it to your phone, and let it finish syncing."
        )
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchall()
    except (sqlite3.OperationalError, sqlite3.DatabaseError, PermissionError) as exc:
        raise WhatsAppDBError(
            f"macOS blocked reading {path} ({exc}). Grant Full Disk Access to the app that "
            "launches this server (Claude, or your terminal) in System Settings > Privacy & "
            "Security > Full Disk Access, then fully quit and reopen that app."
        ) from exc
    conn.row_factory = sqlite3.Row
    return conn


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def has_table(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def jid_to_phone(jid: str | None) -> str | None:
    """'14155550123@s.whatsapp.net' -> '+14155550123'. None for groups / LIDs."""
    if not jid or not jid.endswith("@s.whatsapp.net"):
        return None
    number = jid.split("@", 1)[0].split(":", 1)[0]
    return f"+{number}" if number.isdigit() else None


def push_names(conn: sqlite3.Connection) -> dict[str, str]:
    if not has_table(conn, "ZWAPROFILEPUSHNAME"):
        return {}
    return {
        row["ZJID"]: row["ZPUSHNAME"]
        for row in conn.execute(
            "SELECT ZJID, ZPUSHNAME FROM ZWAPROFILEPUSHNAME WHERE ZPUSHNAME IS NOT NULL"
        )
    }


def chat_names_by_jid(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        row["ZCONTACTJID"]: row["ZPARTNERNAME"]
        for row in conn.execute(
            "SELECT ZCONTACTJID, ZPARTNERNAME FROM ZWACHATSESSION "
            "WHERE ZCONTACTJID IS NOT NULL AND ZPARTNERNAME IS NOT NULL"
        )
    }


def find_chats(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    """Resolve a chat by exact JID, phone number, or (partial) name.

    Exact name matches win over partial ones, so 'Mom' doesn't collide with
    'Mom & Dad' when both exist.
    """
    query = query.strip()
    base = "SELECT * FROM ZWACHATSESSION WHERE COALESCE(ZREMOVED, 0) = 0 AND "
    if "@" in query:
        return conn.execute(base + "ZCONTACTJID = ?", (query,)).fetchall()
    digits = "".join(ch for ch in query if ch.isdigit())
    if digits and len(digits) >= 7 and all(ch in "+-() ." or ch.isdigit() for ch in query):
        rows = conn.execute(
            base + "ZCONTACTJID = ?", (f"{digits}@s.whatsapp.net",)
        ).fetchall()
        if rows:
            return rows
    exact = conn.execute(base + "ZPARTNERNAME = ? COLLATE NOCASE", (query,)).fetchall()
    if exact:
        return exact
    like = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    return conn.execute(
        base + "ZPARTNERNAME LIKE ? ESCAPE '\\' ORDER BY ZLASTMESSAGEDATE DESC", (like,)
    ).fetchall()
