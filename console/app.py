"""FastAPI console: paste trip requirements, watch the pipeline run, get a link.

Run with: uvicorn console.app:app --host 127.0.0.1 --port 8000
"""

import asyncio
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form
from fastapi.responses import FileResponse, HTMLResponse
from sse_starlette.sse import EventSourceResponse

from console import db
from orchestrator import run_travel_planner

app = FastAPI(title="Travel planning console")

STATIC_DIR = Path(__file__).parent / "static"

# In-memory per-trip event queues for SSE; trip_events table is the durable log.
_queues: dict[str, asyncio.Queue] = {}


@app.on_event("startup")
def on_startup():
    db.init_db()


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(STATIC_DIR / "index.html")


def _run_pipeline(trip_id: str, requirements_text: str):
    queue = _queues[trip_id]

    def log(message: str):
        db.add_event(trip_id, message)
        queue.put_nowait(message)

    try:
        db.set_status(trip_id, "running")
        log("Pradedama...")
        page_html = run_travel_planner(requirements_text)
        # TODO: once the CI/CD agent (#9 follow-up) exists, this becomes the
        # real GitHub Pages URL it returns instead of a local marker.
        db.set_status(trip_id, "done", page_url="(CI/CD agent not implemented yet)")
        log("Baigta.")
    except NotImplementedError as e:
        db.set_status(trip_id, "failed")
        log(f"Klaida: {e}")
    except Exception as e:  # noqa: BLE001 - surface any failure to the console log
        db.set_status(trip_id, "failed")
        log(f"Nepavyko: {e}")
    finally:
        queue.put_nowait(None)  # sentinel: stream ends


@app.post("/trips")
def create_trip(background_tasks: BackgroundTasks, requirements_text: str = Form(...)):
    trip_id = uuid.uuid4().hex[:12]
    db.create_trip(trip_id, requirements_text)
    _queues[trip_id] = asyncio.Queue()
    background_tasks.add_task(_run_pipeline, trip_id, requirements_text)
    return {"trip_id": trip_id}


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
