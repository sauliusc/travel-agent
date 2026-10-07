"""Minimal SQLite storage for the console: trip records and their event logs."""

import json
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

CREATE TABLE IF NOT EXISTS trip_stages (
    trip_id TEXT NOT NULL REFERENCES trips(id),
    stage TEXT NOT NULL,
    output TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (trip_id, stage)
);

-- Every real `claude -p` query+response, append-only (unlike trip_stages,
-- which only keeps the latest output per stage) -- a stage can invoke
-- claude more than once (e.g. the critic-fix loop calls itinerary/
-- logistics_report/page repeatedly), and each call is worth keeping so the
-- admin panel can show exactly what was asked and answered without
-- grepping `ps aux`/journalctl on the machine the pipeline runs on.
CREATE TABLE IF NOT EXISTS trip_agent_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id TEXT NOT NULL REFERENCES trips(id),
    stage TEXT NOT NULL,
    query TEXT NOT NULL,
    response TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Columns added after the initial release. CREATE TABLE IF NOT EXISTS is a
# no-op on a table that already exists, so a deployed database from before
# these columns existed needs an explicit, idempotent migration here.
_MIGRATIONS = [
    ("trips", "finished_at", "TEXT"),
    ("trip_events", "level", "TEXT NOT NULL DEFAULT 'info'"),
    ("trip_agent_calls", "meta", "TEXT"),
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
    # finished_at must be cleared (not just left alone) when a trip moves
    # back to "running"/"queued" -- e.g. a step rerun or modify on a
    # previously done/failed trip -- otherwise the UI keeps showing a stale
    # finished timestamp from the trip's earlier run while it's actively
    # running again.
    finished = status in ("done", "failed")
    with connect() as conn:
        if page_url is not None:
            conn.execute(
                "UPDATE trips SET status = ?, page_url = ?, "
                "finished_at = CASE WHEN ? THEN datetime('now') ELSE NULL END "
                "WHERE id = ?",
                (status, page_url, finished, trip_id),
            )
        else:
            conn.execute(
                "UPDATE trips SET status = ?, "
                "finished_at = CASE WHEN ? THEN datetime('now') ELSE NULL END "
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
        conn.execute("DELETE FROM trip_stages WHERE trip_id = ?", (trip_id,))
        conn.execute("DELETE FROM trip_agent_calls WHERE trip_id = ?", (trip_id,))
        conn.execute("DELETE FROM trips WHERE id = ?", (trip_id,))


def save_stage_output(trip_id: str, stage: str, output: str) -> None:
    """Persist one pipeline stage's raw (string) output for a trip.

    Overwrites any previous value for the same (trip_id, stage) -- a rerun
    of that stage replaces it rather than accumulating history, since the
    point is "what should downstream stages use as input now."
    """
    with connect() as conn:
        conn.execute(
            "INSERT INTO trip_stages (trip_id, stage, output) VALUES (?, ?, ?) "
            "ON CONFLICT (trip_id, stage) DO UPDATE SET output = excluded.output, "
            "created_at = datetime('now')",
            (trip_id, stage, output),
        )


def get_stage_outputs(trip_id: str) -> dict[str, str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT stage, output FROM trip_stages WHERE trip_id = ?", (trip_id,)
        ).fetchall()
    return {row["stage"]: row["output"] for row in rows}


def get_events(trip_id: str) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM trip_events WHERE trip_id = ? ORDER BY id ASC", (trip_id,)
        ).fetchall()


def save_agent_call(trip_id: str, stage: str, query: str, response: str, meta: dict | None = None) -> None:
    """Append one real claude -p query+response for a trip's stage.

    Append-only by design (see trip_agent_calls' schema comment) -- a stage
    invoked multiple times (e.g. during the critic-fix loop) keeps every
    call, not just the latest.
    """
    with connect() as conn:
        conn.execute(
            "INSERT INTO trip_agent_calls (trip_id, stage, query, response, meta) VALUES (?, ?, ?, ?, ?)",
            (trip_id, stage, query, response, json.dumps(meta, ensure_ascii=False) if meta else None),
        )


def get_agent_calls(trip_id: str, stage: str | None = None) -> list[sqlite3.Row]:
    """All (or, given `stage`, just that stage's) agent calls for a trip, oldest first."""
    with connect() as conn:
        if stage is not None:
            return conn.execute(
                "SELECT * FROM trip_agent_calls WHERE trip_id = ? AND stage = ? ORDER BY id ASC",
                (trip_id, stage),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM trip_agent_calls WHERE trip_id = ? ORDER BY id ASC", (trip_id,)
        ).fetchall()


def get_call_stage_summary(trip_id: str) -> list[dict]:
    """Distinct stages with recorded calls for a trip, in first-call order,
    each with its call count -- drives the console UI's one-collapsible-
    item-per-stage list. Includes "critic", which has its own calls but
    isn't a trip_stages/STAGE_ORDER entry (its output isn't cached/rerun
    from directly), so this is a superset of get_stage_outputs()'s keys.
    """
    with connect() as conn:
        rows = conn.execute(
            "SELECT stage, COUNT(*) as count, MIN(id) as first_id "
            "FROM trip_agent_calls WHERE trip_id = ? "
            "GROUP BY stage ORDER BY first_id ASC",
            (trip_id,),
        ).fetchall()
    return [{"stage": row["stage"], "count": row["count"]} for row in rows]


def get_agent_overview() -> list[dict]:
    """Per agent stage, across all trips: call count, last call time and the
    latest call's invocation meta (model, tools, prompt file...)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT stage, COUNT(*) AS count, MAX(id) AS last_id, MAX(created_at) AS last_at "
            "FROM trip_agent_calls GROUP BY stage"
        ).fetchall()
        out = []
        for r in rows:
            last = conn.execute(
                "SELECT meta FROM trip_agent_calls WHERE stage = ? AND meta IS NOT NULL ORDER BY id DESC LIMIT 1",
                (r["stage"],),
            ).fetchone()
            out.append({"stage": r["stage"], "count": r["count"], "last_at": r["last_at"],
                        "meta": json.loads(last["meta"]) if last else None})
    return out


def get_recent_agent_calls(stage: str, limit: int = 20) -> list[sqlite3.Row]:
    """Latest calls of one agent stage across all trips, newest first."""
    with connect() as conn:
        return conn.execute(
            "SELECT c.id, c.trip_id, c.created_at, c.query, c.response, c.meta, t.requirements_text "
            "FROM trip_agent_calls c LEFT JOIN trips t ON t.id = c.trip_id "
            "WHERE c.stage = ? ORDER BY c.id DESC LIMIT ?",
            (stage, limit),
        ).fetchall()
