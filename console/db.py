"""Minimal SQLite storage for the console: trip records and their event logs."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "console.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS trips (
    id TEXT PRIMARY KEY,
    requirements_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    page_url TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trip_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id TEXT NOT NULL REFERENCES trips(id),
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)


def create_trip(trip_id: str, requirements_text: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO trips (id, requirements_text) VALUES (?, ?)",
            (trip_id, requirements_text),
        )


def add_event(trip_id: str, message: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO trip_events (trip_id, message) VALUES (?, ?)", (trip_id, message)
        )


def set_status(trip_id: str, status: str, page_url: str | None = None) -> None:
    with connect() as conn:
        if page_url is not None:
            conn.execute(
                "UPDATE trips SET status = ?, page_url = ? WHERE id = ?",
                (status, page_url, trip_id),
            )
        else:
            conn.execute("UPDATE trips SET status = ? WHERE id = ?", (status, trip_id))


def list_trips() -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute("SELECT * FROM trips ORDER BY created_at DESC").fetchall()


def get_events(trip_id: str) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM trip_events WHERE trip_id = ? ORDER BY id ASC", (trip_id,)
        ).fetchall()
