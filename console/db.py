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
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS trip_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id TEXT NOT NULL REFERENCES trips(id),
    message TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Columns added after the initial release. CREATE TABLE IF NOT EXISTS is a
# no-op on a table that already exists, so a deployed database from before
# these columns existed needs an explicit, idempotent migration here.
_MIGRATIONS = [
    ("trips", "finished_at", "TEXT"),
    ("trip_events", "level", "TEXT NOT NULL DEFAULT 'info'"),
]


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, coltype in _MIGRATIONS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def create_trip(trip_id: str, requirements_text: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO trips (id, requirements_text) VALUES (?, ?)",
            (trip_id, requirements_text),
        )


def add_event(trip_id: str, message: str, level: str = "info") -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO trip_events (trip_id, message, level) VALUES (?, ?, ?)",
            (trip_id, message, level),
        )


def set_status(trip_id: str, status: str, page_url: str | None = None) -> None:
    finished = status in ("done", "failed")
    with connect() as conn:
        if page_url is not None:
            conn.execute(
                "UPDATE trips SET status = ?, page_url = ?, "
                "finished_at = CASE WHEN ? THEN datetime('now') ELSE finished_at END "
                "WHERE id = ?",
                (status, page_url, finished, trip_id),
            )
        else:
            conn.execute(
                "UPDATE trips SET status = ?, "
                "finished_at = CASE WHEN ? THEN datetime('now') ELSE finished_at END "
                "WHERE id = ?",
                (status, finished, trip_id),
            )


def list_trips() -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute("SELECT * FROM trips ORDER BY created_at DESC").fetchall()


def get_trip(trip_id: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()


def delete_trip(trip_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM trip_events WHERE trip_id = ?", (trip_id,))
        conn.execute("DELETE FROM trips WHERE id = ?", (trip_id,))


def get_events(trip_id: str) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM trip_events WHERE trip_id = ? ORDER BY id ASC", (trip_id,)
        ).fetchall()
