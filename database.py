import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;

                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT NOT NULL,
                    start_count INTEGER NOT NULL DEFAULT 1,
                    started_at TEXT NOT NULL,
                    phone TEXT,
                    phone_received_at TEXT
                );

                CREATE TABLE IF NOT EXISTS scheduled_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(user_id),
                    sequence INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL,
                    sent_at TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    UNIQUE(user_id, sequence)
                );

                CREATE INDEX IF NOT EXISTS scheduled_messages_due
                    ON scheduled_messages(status, scheduled_at);
                """
            )

    def register_start(self, user_id: int, username: str | None, first_name: str) -> None:
        now = timestamp()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO users (user_id, username, first_name, started_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    start_count = users.start_count + 1
                """,
                (user_id, username, first_name, now),
            )

    def has_phone(self, user_id: int) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT phone_received_at FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return bool(row and row["phone_received_at"])

    def register_phone(
        self,
        user_id: int,
        phone: str,
        messages: list[dict[str, Any]],
    ) -> bool:
        now = utc_now()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT phone FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            if row is None:
                return False
            if row["phone"]:
                return False

            connection.execute(
                "UPDATE users SET phone = ?, phone_received_at = ? WHERE user_id = ?",
                (phone, timestamp(now), user_id),
            )
            for sequence, message in enumerate(messages, start=1):
                due_at = now + timedelta(seconds=int(message["delay_seconds"]))
                connection.execute(
                    """
                    INSERT OR IGNORE INTO scheduled_messages
                        (user_id, sequence, text, scheduled_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, sequence, message["text"], timestamp(due_at)),
                )
        return True

    def due_messages(self) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT id, user_id, text
                FROM scheduled_messages
                WHERE status = 'pending' AND scheduled_at <= ?
                ORDER BY scheduled_at, id
                LIMIT 50
                """,
                (timestamp(),),
            ).fetchall()

    def mark_message(self, message_id: int, status: str) -> None:
        sent_at = timestamp() if status == "sent" else None
        with self.connect() as connection:
            connection.execute(
                "UPDATE scheduled_messages SET status = ?, sent_at = ? WHERE id = ?",
                (status, sent_at, message_id),
            )

    def dashboard_stats(self) -> dict[str, Any]:
        with self.connect() as connection:
            totals = connection.execute(
                """
                SELECT
                    COALESCE(SUM(start_count), 0) AS starts,
                    COUNT(*) AS users,
                    SUM(CASE WHEN phone_received_at IS NOT NULL THEN 1 ELSE 0 END) AS phones
                FROM users
                """
            ).fetchone()
            sent = connection.execute(
                "SELECT COUNT(*) FROM scheduled_messages WHERE status = 'sent'"
            ).fetchone()[0]
            recent = connection.execute(
                """
                SELECT started_at, phone_received_at
                FROM users
                ORDER BY started_at DESC
                LIMIT 10
                """
            ).fetchall()

        starts = int(totals["starts"] or 0)
        phones = int(totals["phones"] or 0)
        return {
            "starts": starts,
            "users": int(totals["users"] or 0),
            "phones": phones,
            "conversion": round(phones / starts * 100, 1) if starts else 0,
            "messages_sent": int(sent),
            "recent_users": [
                {
                    "name": f"Пользователь {index}",
                    "started_at": row["started_at"],
                    "phone_received": bool(row["phone_received_at"]),
                }
                for index, row in enumerate(recent, start=1)
            ],
        }

