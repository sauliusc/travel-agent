"""FastAPI console: paste trip requirements, watch the pipeline run, get a link.

Run with: uvicorn console.app:app --host 127.0.0.1 --port 8000
"""

import asyncio
import html
import logging
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from sse_starlette.sse import EventSourceResponse

from console import config, db
from orchestrator import run_travel_planner

app = FastAPI(title="Travel planning console")

STATIC_DIR = Path(__file__).parent / "static"
logger = logging.getLogger("travel-console")

# In-memory per-trip event queues for SSE; trip_events table is the durable log.
_queues: dict[str, asyncio.Queue] = {}


@app.on_event("startup")
def on_startup():
    db.init_db()
    problems = config.require_credentials()
    for problem in problems:
        logger.warning("Startup credential check: %s", problem)
    if problems:
        logger.warning(
            "The console will start, but any trip run will fail until these are fixed "
            "(see .env.example / docs/PROXMOX_SETUP.md)."
        )


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(STATIC_DIR / "index.html")


def _run_pipeline(trip_id: str, requirements_text: str):
    queue = _queues[trip_id]

    def log(message: str, level: str = "info"):
        db.add_event(trip_id, message, level)
        queue.put_nowait(message)

    try:
        db.set_status(trip_id, "running")
        log("Pradedama...")
        page_html = run_travel_planner(requirements_text, on_progress=log)
        # TODO: once the CI/CD agent returns a real URL, wire it in here
        # instead of this placeholder.
        db.set_status(trip_id, "done", page_url="(CI/CD agent not implemented yet)")
        log("Baigta.")
    except NotImplementedError as e:
        db.set_status(trip_id, "failed")
        log(f"Klaida: {e}", level="error")
    except Exception as e:  # noqa: BLE001 - surface any failure to the console log
        db.set_status(trip_id, "failed")
        log(f"Nepavyko: {e}", level="error")
    finally:
        queue.put_nowait(None)  # sentinel: stream ends


@app.post("/trips")
def create_trip(background_tasks: BackgroundTasks, requirements_text: str = Form(...)):
    trip_id = uuid.uuid4().hex[:12]
    db.create_trip(trip_id, requirements_text)
    _queues[trip_id] = asyncio.Queue()
    background_tasks.add_task(_run_pipeline, trip_id, requirements_text)
    return {"trip_id": trip_id}


@app.post("/trips/{trip_id}/retry")
def retry_trip(trip_id: str, background_tasks: BackgroundTasks):
    original = db.get_trip(trip_id)
    if original is None:
        raise HTTPException(404, "Trip not found")
    new_id = uuid.uuid4().hex[:12]
    db.create_trip(new_id, original["requirements_text"])
    _queues[new_id] = asyncio.Queue()
    background_tasks.add_task(_run_pipeline, new_id, original["requirements_text"])
    return {"trip_id": new_id}


@app.delete("/trips/{trip_id}")
def delete_trip(trip_id: str):
    if db.get_trip(trip_id) is None:
        raise HTTPException(404, "Trip not found")
    db.delete_trip(trip_id)
    _queues.pop(trip_id, None)
    return {"deleted": trip_id}


@app.get("/trips/{trip_id}/events")
async def trip_events(trip_id: str):
    queue = _queues.get(trip_id)

    async def event_generator():
        if queue is None:
            # Trip from a previous process run: replay the stored log, then close.
            for row in db.get_events(trip_id):
                yield {"data": row["message"]}
            return
        while True:
            message = await queue.get()
            if message is None:
                break
            yield {"data": message}

    return EventSourceResponse(event_generator())


@app.get("/trips")
def trips():
    return [dict(row) for row in db.list_trips()]


_STATUS_LABELS = {"queued": "Laukia", "running": "Vykdoma", "done": "Baigta", "failed": "Nepavyko"}


def _render_trip_item(trip: dict) -> str:
    title = html.escape(trip["requirements_text"][:90].replace("\n", " "))
    status = trip["status"]
    label = html.escape(_STATUS_LABELS.get(status, status))
    created = html.escape((trip["created_at"] or "")[:16])
    trip_id = html.escape(trip["id"])
    return (
        f'<div class="trip-item" data-trip-id="{trip_id}" onclick="openTrip(\'{trip_id}\')">'
        f'<div class="title">{title}</div>'
        f'<div class="trip-row">'
        f'<span class="badge {status}">{label}</span>'
        f'<span class="trip-time">{created}</span>'
        f"</div></div>"
    )


@app.get("/trips/list", response_class=HTMLResponse)
def trips_list_html():
    """HTML fragment for the sidebar, polled by HTMX (hx-trigger="load, every 5s")."""
    rows = db.list_trips()
    if not rows:
        return '<div class="empty-list">Kol kas nėra kelionių.</div>'
    return "".join(_render_trip_item(dict(row)) for row in rows)


@app.get("/trips/{trip_id}")
def trip_detail(trip_id: str):
    trip = db.get_trip(trip_id)
    if trip is None:
        raise HTTPException(404, "Trip not found")
    events = db.get_events(trip_id)
    return {
        **dict(trip),
        "events": [dict(row) for row in events],
    }
