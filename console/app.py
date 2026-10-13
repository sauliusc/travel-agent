"""FastAPI console: paste trip requirements, watch the pipeline run, get a link.

Run with: uvicorn console.app:app --host 127.0.0.1 --port 8000
"""

import asyncio
import importlib
import json
import re
import html
import logging
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, Body, FastAPI, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sse_starlette.sse import EventSourceResponse

from agents import providers
from console import config, db
from tools import run_history
from orchestrator import CODE_STAGES, STAGE_LABELS, STAGE_ORDER, STAGE_PROMPTS, run_from_stage, run_travel_planner

app = FastAPI(title="Travel planning console")

STATIC_DIR = Path(__file__).parent / "static"
logger = logging.getLogger("travel-console")

# trip_stages key (not a pipeline stage) holding where a failed run should resume.
RESUME_KEY = "_resume"

# In-memory per-trip event queues for SSE; trip_events table is the durable log.
_queues: dict[str, asyncio.Queue] = {}


@app.on_event("startup")
def on_startup():
    db.init_db()
    # Agents with a configured AI provider run on it instead of claude -p.
    providers.set_resolver(db.provider_for_stage)
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
    # no-cache: revalidate on every load. Without it a phone kept showing the
    # pre-update page from its cache (heuristic freshness), so a deployed
    # layout fix looked like it hadn't worked.
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


def _run_pipeline(
    trip_id: str,
    requirements_text: str,
    stage_name: str = "requirements",
    cached_outputs: dict[str, str] | None = None,
    modification: str | None = None,
    change_notes: list[str] | None = None,
):
    """Run (or resume, or modify) a trip's pipeline in the background.

    A plain new/retried trip calls this with the defaults (start at
    "requirements", no cache). A step rerun passes a later `stage_name`
    plus that trip's `cached_outputs` (see /trips/{id}/rerun-from/{stage}).
    A free-text modification passes stage_name="accommodation" plus
    `modification` (see /trips/{id}/modify).
    """
    queue = _queues[trip_id]
    done_this_run: list[str] = []
    # Collected for this run's request-history/*.md in the trip repository.
    started = run_history.now()
    events: list[tuple] = []
    calls: list[dict] = []
    if modification is not None:
        kind, kind_slug = "Pataisymas", "pataisymas"
    elif stage_name == "requirements" and not cached_outputs:
        kind, kind_slug = "Pradinė užklausa", "pradine-uzklausa"
    else:
        kind = f"Perleidimas nuo žingsnio „{STAGE_LABELS.get(stage_name, stage_name)}“"
        kind_slug = f"perleidimas-{stage_name}"

    def record_call(stage, query, response, meta=None):
        db.save_agent_call(trip_id, stage, query, response, meta)
        calls.append({"time": run_history.now(), "stage": stage, "query": query,
                      "response": response, "meta": meta})

    def save_history(page_url: str | None, status: str, error: str | None = None) -> None:
        m = re.match(r"https://([^.]+)\.github\.io/([^/]+)/?", page_url or "")
        if not m:
            return  # no trip repository yet (first run failed before publishing)
        try:
            path = run_history.publish(m.group(1), m.group(2), {
                "kind": kind, "kind_slug": kind_slug, "started": started, "finished": run_history.now(),
                "trip_id": trip_id, "profile": profile_name, "status": status, "error": error,
                "modification": modification, "events": events, "calls": calls,
            })
            log(f"Užklausų istorija: {path}")
        except Exception as e:  # noqa: BLE001 - history is a bonus, never fails the run
            log(f"Užklausų istorijos išsaugoti nepavyko: {e}", level="error")

    def stage_complete(stage: str, output: str) -> None:
        db.save_stage_output(trip_id, stage, output)
        if stage in STAGE_ORDER:
            done_this_run.append(stage)

    def remember_resume_point() -> None:
        # Where "↻ Bandyti dar kartą" continues: right after the last stage
        # this run finished. A modification not yet applied to the itinerary
        # is kept, so it's applied on retry instead of being lost.
        last = max((STAGE_ORDER.index(s) for s in done_this_run), default=None)
        resume = stage_name if last is None else STAGE_ORDER[min(last + 1, len(STAGE_ORDER) - 1)]
        itinerary_done = "itinerary" in done_this_run
        request = modification or (change_notes[0] if change_notes else None)
        db.save_stage_output(trip_id, RESUME_KEY, json.dumps({
            "stage": "accommodation" if modification and not itinerary_done else resume,
            "modification": modification if modification and not itinerary_done else None,
            # Already in the itinerary, but the page still has to show it.
            "note": request if request and (itinerary_done or not modification) else None,
        }, ensure_ascii=False))

    profile_name = None

    def log(message: str, level: str = "info"):
        events.append((run_history.now(), message))
        db.add_event(trip_id, message, level)
        queue.put_nowait(message)

    try:
        db.set_status(trip_id, "running")
        if modification is not None:
            log(f"Taikomas pataisymas: {modification}")
        else:
            log("Pradedama..." if stage_name == "requirements" else f"Perleidžiama nuo žingsnio: {stage_name}...")
        trip = db.get_trip(trip_id)
        profile_id = trip["profile_id"] if trip is not None else None
        profile = db.get_profile(profile_id or db.BASE_PROFILE)
        profile_name = profile["name"] if profile else None
        if profile and profile["id"] != db.BASE_PROFILE:
            log(f"Agentų rinkinys: {profile['name']}")
        with providers.using_profile(profile_id):
            url = run_from_stage(
                stage_name,
                cached_outputs=cached_outputs,
                on_progress=log,
                on_stage_complete=stage_complete,
                on_llm_call=record_call,
                modification=modification,
                user_requirements=requirements_text,
                change_notes=change_notes,
            )
        db.save_stage_output(trip_id, RESUME_KEY, "")
        db.set_status(trip_id, "done", page_url=url)
        log(f"Puslapis paskelbtas: {url}")
        save_history(url, "done")
        log("Baigta.")
    except NotImplementedError as e:
        remember_resume_point()
        db.set_status(trip_id, "failed")
        log(f"Klaida: {e}", level="error")
        save_history(_trip_page_url(trip_id), "failed", str(e))
    except Exception as e:  # noqa: BLE001 - surface any failure to the console log
        remember_resume_point()
        db.set_status(trip_id, "failed")
        log(f"Nepavyko: {e}", level="error")
        save_history(_trip_page_url(trip_id), "failed", str(e))
    finally:
        queue.put_nowait(None)  # sentinel: stream ends


def _trip_page_url(trip_id: str) -> str | None:
    trip = db.get_trip(trip_id)
    return trip["page_url"] if trip is not None else None


@app.post("/trips")
def create_trip(background_tasks: BackgroundTasks, requirements_text: str = Form(...),
                profile_id: int | None = Form(None)):
    if profile_id is not None and db.get_profile(profile_id) is None:
        raise HTTPException(400, "Unknown agent set")
    trip_id = uuid.uuid4().hex[:12]
    db.create_trip(trip_id, requirements_text, profile_id)
    _queues[trip_id] = asyncio.Queue()
    background_tasks.add_task(_run_pipeline, trip_id, requirements_text)
    return {"trip_id": trip_id}


def _legacy_resume_point(trip_id: str, cached: dict) -> tuple[str, str | None]:
    """Resume point for a run that failed before RESUME_KEY existed: a
    modification whose run never finished is re-applied; otherwise the first
    stage without output, else "forecast" (code-only -- later stages rerun
    only if their inputs changed)."""
    events = [e["message"] for e in db.get_events(trip_id)]
    for msg in reversed(events):
        if msg == "Baigta.":
            break
        if msg.startswith("Taikomas pataisymas: "):
            return "accommodation", msg[len("Taikomas pataisymas: "):]
    return next((s for s in STAGE_ORDER if s not in cached), "forecast"), None


@app.post("/trips/{trip_id}/retry")
def retry_trip(trip_id: str, background_tasks: BackgroundTasks):
    """Continue the same trip from where it failed, reusing finished stages
    (and re-applying a modification that hadn't reached the itinerary yet).
    Never creates a new trip."""
    trip = db.get_trip(trip_id)
    if trip is None:
        raise HTTPException(404, "Trip not found")
    if trip["status"] in ("running", "queued"):
        raise HTTPException(409, "Trip is already running")
    cached = db.get_stage_outputs(trip_id)
    resume = json.loads(cached.get(RESUME_KEY) or "null") or {}
    stage, modification = resume.get("stage"), resume.get("modification")
    if stage not in STAGE_ORDER:
        stage, modification = _legacy_resume_point(trip_id, cached)
    db.set_status(trip_id, "queued")
    _queues[trip_id] = asyncio.Queue()
    note = resume.get("note")
    background_tasks.add_task(_run_pipeline, trip_id, trip["requirements_text"], stage,
                              cached, modification, [note] if note else None)
    return {"trip_id": trip_id, "stage": stage}


@app.post("/trips/{trip_id}/rerun-from/{stage}")
def rerun_trip_from_stage(trip_id: str, stage: str, background_tasks: BackgroundTasks):
    """Rerun an existing trip's pipeline starting at `stage`, reusing its
    already-persisted earlier stage outputs -- updates the same trip
    record rather than creating a new one.
    """
    trip = db.get_trip(trip_id)
    if trip is None:
        raise HTTPException(404, "Trip not found")
    if stage not in STAGE_ORDER:
        raise HTTPException(400, f"Unknown stage {stage!r}, must be one of {STAGE_ORDER}")
    cached = db.get_stage_outputs(trip_id)
    missing = [s for s in STAGE_ORDER[: STAGE_ORDER.index(stage)] if s not in cached and s not in CODE_STAGES]
    if missing:
        raise HTTPException(400, f"Missing cached output for earlier stage(s): {missing}")
    # Set status before returning (not just inside the background task) so a
    # client that immediately re-fetches the trip sees "queued", not the
    # stale done/failed status from before this rerun was requested.
    db.set_status(trip_id, "queued")
    _queues[trip_id] = asyncio.Queue()
    background_tasks.add_task(
        _run_pipeline, trip_id, trip["requirements_text"], stage, cached, None
    )
    return {"trip_id": trip_id, "stage": stage}


@app.post("/trips/{trip_id}/modify")
def modify_trip(trip_id: str, background_tasks: BackgroundTasks, modification: str = Form(...)):
    """Apply a free-text modification to an existing trip's itinerary,
    without rebuilding requirements/research/weather/accommodation.
    """
    trip = db.get_trip(trip_id)
    if trip is None:
        raise HTTPException(404, "Trip not found")
    cached = db.get_stage_outputs(trip_id)
    missing = [s for s in ("requirements", "research", "weather", "accommodation", "itinerary") if s not in cached]
    if missing:
        raise HTTPException(400, f"Trip has no completed {', '.join(missing)} yet to modify")
    db.set_status(trip_id, "queued")
    _queues[trip_id] = asyncio.Queue()
    # From accommodation: the change is applied to lodging (if it concerns it)
    # and the itinerary; every later stage reruns only if its inputs changed.
    background_tasks.add_task(
        _run_pipeline, trip_id, trip["requirements_text"], "accommodation", cached, modification
    )
    return {"trip_id": trip_id}


@app.delete("/trips/{trip_id}")
def delete_trip(trip_id: str):
    if db.get_trip(trip_id) is None:
        raise HTTPException(404, "Trip not found")
    db.delete_trip(trip_id)
    _queues.pop(trip_id, None)
    return {"deleted": trip_id}


@app.post("/trips/delete")
def delete_trips(payload: dict = Body(...)):
    """Delete several trips with all their history; running/queued trips are skipped."""
    deleted, skipped = [], []
    for trip_id in payload.get("ids", []):
        trip = db.get_trip(trip_id)
        if trip is None:
            continue
        if trip["status"] in ("running", "queued"):
            skipped.append(trip_id)
            continue
        db.delete_trip(trip_id)
        _queues.pop(trip_id, None)
        deleted.append(trip_id)
    return {"deleted": deleted, "skipped": skipped}


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
        f'<div class="trip-item" data-trip-id="{trip_id}" data-status="{html.escape(status)}" '
        f'data-created="{created}" onclick="tripClick(event, \'{trip_id}\')">'
        f'<input type="checkbox" class="trip-select" tabindex="-1" aria-label="Pažymėti">'
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
    stage_outputs = db.get_stage_outputs(trip_id)
    return {
        **dict(trip),
        "events": [dict(row) for row in events],
        # Which stages have a persisted output to rerun from -- in pipeline
        # order, so the UI can offer "Perleisti nuo čia" per completed stage.
        "completed_stages": [s for s in STAGE_ORDER if s in stage_outputs],
        # Every stage that has made at least one real claude -p call (a
        # superset of completed_stages -- includes "critic", and includes a
        # stage that's mid-run with no persisted output yet) -- drives the
        # collapsible per-stage call log in the UI.
        "call_stages": db.get_call_stage_summary(trip_id),
        "profile": db.get_profile(trip["profile_id"] or db.BASE_PROFILE),
    }


@app.get("/trips/{trip_id}/stages/{stage}/calls")
def trip_stage_calls(trip_id: str, stage: str):
    """The full query+response of every real claude -p call made for one
    stage of one trip -- fetched on demand when a UI stage item is
    expanded, so the admin panel is the source of truth for "what was
    asked and answered" instead of journalctl/ps aux on the host.
    """
    if db.get_trip(trip_id) is None:
        raise HTTPException(404, "Trip not found")
    calls = db.get_agent_calls(trip_id, stage=stage)
    return [dict(row) for row in calls]


# --- /agents: what each agent is and how it was actually invoked ----------
# Stages that call an LLM agent (map_data, forecast, deploy_log are code),
# with the agents/ module implementing each.
AGENT_MODULES = {
    "requirements": "requirements", "research": "research", "weather": "weather",
    "accommodation": "accommodation", "itinerary": "itinerary", "logistics_report": "logistics",
    "images": "images", "car_rental": "car_rental", "food": "food", "plan_b": "plan_b",
    "packing": "packing", "budget": "budget", "page": "page_designer", "critic": "critic",
}
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _agent_description(module: str) -> str:
    try:
        doc = importlib.import_module(f"agents.{module}").__doc__ or ""
    except Exception:
        return ""
    return doc.strip().split("\n\n")[0].replace("\n", " ")


@app.get("/settings", response_class=HTMLResponse)
def settings_page():
    return FileResponse(STATIC_DIR / "settings.html", headers={"Cache-Control": "no-cache"})


@app.get("/agents")
def agents_page():
    # Old address; the agents view now lives under settings.
    return RedirectResponse("/settings#agents")


@app.get("/api/agents")
def agents_overview(profile_id: int = 1):
    stats = {row["stage"]: row for row in db.get_agent_overview()}
    assigned = db.agent_provider_ids(profile_id)
    out = []
    for stage, module in AGENT_MODULES.items():
        prompt_file = ("critic.md" if stage == "critic" else (STAGE_PROMPTS.get(stage) or [None])[0])
        prompt = (PROMPTS_DIR / prompt_file).read_text() if prompt_file and (PROMPTS_DIR / prompt_file).exists() else ""
        st = stats.get(stage, {})
        out.append({
            "provider_id": assigned.get(stage),
            "needs_bash": stage in providers.BASH_AGENTS,
            "stage": stage, "label": STAGE_LABELS.get(stage, "Peržiūra" if stage == "critic" else stage),
            "module": f"agents/{module}.py", "description": _agent_description(module),
            "prompt_file": prompt_file, "prompt": prompt,
            "count": st.get("count", 0), "last_at": st.get("last_at"), "meta": st.get("meta"),
        })
    return out


@app.get("/api/agents/{stage}/calls")
def agent_calls(stage: str, limit: int = 20):
    rows = db.get_recent_agent_calls(stage, min(limit, 100))
    return [{**{k: r[k] for k in ("id", "trip_id", "created_at", "query", "response")},
             "trip": (r["requirements_text"] or "")[:120],
             "meta": json.loads(r["meta"]) if r["meta"] else None} for r in rows]


# --- AI providers (⚙️ Nustatymai → AI tiekėjai) -------------------------------

def _provider_payload(data: dict, creating: bool) -> dict:
    out = {k: (str(data.get(k) or "").strip() or None) for k in ("name", "type", "base_url", "model", "api_key")}
    if out["type"] not in providers.PROVIDER_TYPES:
        raise HTTPException(400, f"type must be one of {list(providers.PROVIDER_TYPES)}")
    if not out["name"] or not out["model"]:
        raise HTTPException(400, "name and model are required")
    if creating and not out["api_key"]:
        raise HTTPException(400, "api_key is required")
    return out


@app.get("/api/providers")
def list_ai_providers():
    return {"types": providers.PROVIDER_TYPES, "providers": db.list_providers()}


@app.post("/api/providers")
def create_ai_provider(data: dict = Body(...)):
    return {"id": db.save_provider(_provider_payload(data, creating=True))}


@app.put("/api/providers/{provider_id}")
def update_ai_provider(provider_id: int, data: dict = Body(...)):
    if db.get_provider(provider_id) is None:
        raise HTTPException(404, "Provider not found")
    return {"id": db.save_provider(_provider_payload(data, creating=False), provider_id)}


@app.delete("/api/providers/{provider_id}")
def delete_ai_provider(provider_id: int):
    db.delete_provider(provider_id)
    return {"deleted": provider_id}


@app.post("/api/providers/{provider_id}/test")
def test_ai_provider(provider_id: int):
    p = db.get_provider(provider_id)
    if p is None:
        raise HTTPException(404, "Provider not found")
    try:
        payload = providers.call(p, "You are a connectivity check.", "Reply with exactly: OK", [], None, 60)
    except providers.ProviderError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "reply": payload["result"][:200]}


@app.put("/api/agents/{stage}/provider")
def set_agent_ai_provider(stage: str, data: dict = Body(...)):
    if stage not in AGENT_MODULES:
        raise HTTPException(404, "Unknown agent")
    profile_id = int(data.get("profile_id") or db.BASE_PROFILE)
    if profile_id == db.BASE_PROFILE:
        raise HTTPException(400, "Base rinkinys nekeičiamas -- nukopijuok jį ir keisk kopiją")
    if db.get_profile(profile_id) is None:
        raise HTTPException(404, "Unknown agent set")
    provider_id = data.get("provider_id")
    if provider_id is not None:
        if stage in providers.BASH_AGENTS:
            raise HTTPException(400, "This agent runs project tools via Bash -- only native Claude can do that")
        if db.get_provider(int(provider_id)) is None:
            raise HTTPException(404, "Provider not found")
        provider_id = int(provider_id)
    db.set_agent_provider(profile_id, stage, provider_id)
    return {"stage": stage, "provider_id": provider_id, "profile_id": profile_id}


# --- agent sets (rinkiniai) ---------------------------------------------------

@app.get("/api/profiles")
def list_agent_profiles():
    return {"base_id": db.BASE_PROFILE, "profiles": db.list_profiles()}


@app.post("/api/profiles")
def copy_agent_profile(data: dict = Body(...)):
    name = str(data.get("name") or "").strip()
    source = int(data.get("copy_from") or db.BASE_PROFILE)
    if not name:
        raise HTTPException(400, "Nurodyk pavadinimą")
    if db.get_profile(source) is None:
        raise HTTPException(404, "Unknown agent set")
    if any(p["name"].lower() == name.lower() for p in db.list_profiles()):
        raise HTTPException(400, "Toks pavadinimas jau yra")
    return {"id": db.copy_profile(source, name)}


@app.put("/api/profiles/{profile_id}")
def rename_agent_profile(profile_id: int, data: dict = Body(...)):
    name = str(data.get("name") or "").strip()
    if profile_id == db.BASE_PROFILE:
        raise HTTPException(400, "Base rinkinio pervadinti negalima")
    if not name or db.get_profile(profile_id) is None:
        raise HTTPException(400, "Bad request")
    db.rename_profile(profile_id, name)
    return {"id": profile_id}


@app.delete("/api/profiles/{profile_id}")
def delete_agent_profile(profile_id: int):
    if profile_id == db.BASE_PROFILE:
        raise HTTPException(400, "Base rinkinio ištrinti negalima")
    db.delete_profile(profile_id)
    return {"deleted": profile_id}
