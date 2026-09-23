"""Main orchestration flow: requirements -> research/weather -> accommodation ->
itinerary -> logistics validation -> map/images/budget -> page -> critic loop ->
CI/CD deploy.

All 14 agents from the design doc are wired in.
"""

import os
import re

from agents.accommodation import find as run_accommodation
from agents.budget import estimate as run_budget
from agents.cicd import deploy as run_cicd
from agents.critic import MAX_FIX_ITERATIONS, review
from agents.images import fetch_images as run_images
from agents.itinerary import fix, plan
from agents.logistics import validate
from agents.map_agent import build_map_data as run_map
from agents.page_designer import design as run_page_designer
from agents.requirements import analyze as run_requirements_analyst
from agents.research import research as run_research
from agents.weather import check as run_weather
from schemas.images import ImageResults
from schemas.requirements import TripRequirements

REPO_PREFIX = "ai-trip-"

# Pipeline stages in dependency order. run_from_stage() uses this to decide,
# for a given starting stage, which earlier stages can be taken from
# cached_outputs (schemas/console.db's trip_stages) instead of recomputed.
STAGE_ORDER = [
    "requirements",
    "research",
    "weather",
    "accommodation",
    "itinerary",
    "logistics_report",
    "map_data",
    "images",
    "budget",
    "page",
    "deploy_log",
]


def _slugify(requirements) -> str:
    base = f"{requirements.destination}-{requirements.trip_type}"
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    return f"{REPO_PREFIX}{slug}"


def run_from_stage(
    stage_name: str,
    cached_outputs: dict[str, str] | None = None,
    on_progress=None,
    on_stage_complete=None,
    modification: str | None = None,
    user_requirements: str | None = None,
) -> str:
    """Run the pipeline starting at `stage_name`, reusing cached_outputs for
    everything before it, and continue through to CI/CD deploy.

    Every stage from `stage_name` onward is recomputed, since each stage
    depends on the ones before it (e.g. a fresh itinerary means map/images/
    budget/page must all be rebuilt too, even if this call started at
    "itinerary" specifically).

    Args:
        stage_name: one of STAGE_ORDER -- where to start (re)computing from
        cached_outputs: previously persisted stage outputs (see
            console/db.py's trip_stages), keyed by stage name -- required
            for every stage strictly before `stage_name`
        on_progress: see run_travel_planner
        on_stage_complete: see run_travel_planner
        modification: optional free-text instruction applied only when
            `stage_name` is exactly "itinerary" -- routes through
            agents.itinerary.fix() against the cached itinerary instead of
            plan() from scratch, so a trip can be tweaked without
            re-deriving the whole day plan
        user_requirements: free-text trip request; required only when
            `stage_name` is "requirements" (i.e. a full fresh run)
    """
    if stage_name not in STAGE_ORDER:
        raise ValueError(f"Unknown stage {stage_name!r}, must be one of {STAGE_ORDER}")

    cached_outputs = cached_outputs or {}
    progress = on_progress or (lambda _msg: None)
    stage_done = on_stage_complete or (lambda _stage, _output: None)
    start_idx = STAGE_ORDER.index(stage_name)
    recompute = False

    def reached(stage: str) -> bool:
        nonlocal recompute
        if not recompute and STAGE_ORDER.index(stage) >= start_idx:
            recompute = True
        return recompute

    if reached("requirements"):
        if user_requirements is None:
            raise ValueError("user_requirements is required to (re)run the requirements stage")
        progress("Reikalavimų analizė...")
        requirements = run_requirements_analyst(user_requirements)
        requirements_json = requirements.model_dump_json()
        stage_done("requirements", requirements_json)
    else:
        requirements_json = cached_outputs["requirements"]
        requirements = TripRequirements.model_validate_json(requirements_json)

    if reached("research"):
        progress("Tyrimas (kelionės objektai, keliai, sezoniškumas)...")
        research = run_research(requirements_json)
        stage_done("research", research)
    else:
        research = cached_outputs["research"]

    if reached("weather"):
        progress("Orų/sezono patikra...")
        weather = run_weather(requirements_json)
        stage_done("weather", weather)
    else:
        weather = cached_outputs["weather"]

    if reached("accommodation"):
        progress("Nakvynės paieška...")
        accommodation = run_accommodation(f"requirements={requirements_json}\nresearch={research}")
        stage_done("accommodation", accommodation)
    else:
        accommodation = cached_outputs["accommodation"]

    if reached("itinerary"):
        if modification is not None and stage_name == "itinerary":
            progress("Dienų plano koregavimas pagal nurodymą...")
            itinerary = fix(cached_outputs["itinerary"], modification)
        else:
            progress("Dienų plano sudarymas...")
            itinerary = plan(
                f"requirements={requirements_json}\nresearch={research}\n"
                f"weather={weather}\naccommodation={accommodation}"
            )
        stage_done("itinerary", itinerary)
    else:
        itinerary = cached_outputs["itinerary"]

    if reached("logistics_report"):
        progress("Logistikos patikra (važiavimo laikai, keliai)...")
        logistics_report = validate(itinerary)
        stage_done("logistics_report", logistics_report)
    else:
        logistics_report = cached_outputs["logistics_report"]

    if reached("map_data"):
        progress("Žemėlapio duomenų ruošimas...")
        map_data = run_map(itinerary)
        stage_done("map_data", map_data)
    else:
        map_data = cached_outputs["map_data"]

    if reached("images"):
        progress("Nuotraukų paieška...")
        images = run_images(itinerary)
        stage_done("images", images.model_dump_json())
    else:
        images = ImageResults.model_validate_json(cached_outputs["images"])
    # run_page_designer's context gets json.dumps'd, which can't serialize a
    # Pydantic model directly -- pass the plain-dict form there, keep the
    # typed ImageResults for run_cicd (which needs .images/.license, not a dict).
    images_for_page = images.model_dump()

    if reached("budget"):
        progress("Biudžeto skaičiavimas...")
        budget = run_budget({"itinerary": itinerary, "accommodation": accommodation})
        stage_done("budget", budget)
    else:
        budget = cached_outputs["budget"]

    page_freshly_built = reached("page")
    if page_freshly_built:
        progress("Puslapio generavimas...")
        page = run_page_designer({"itinerary": itinerary, "map_data": map_data, "images": images_for_page})
        stage_done("page", page)
    else:
        page = cached_outputs["page"]

    # Only worth re-critiquing a page we actually just (re)built -- if this
    # call only touches deploy_log, the cached page already passed review.
    if page_freshly_built:
        for attempt in range(MAX_FIX_ITERATIONS):
            progress(f"Peržiūra (bandymas {attempt + 1}/{MAX_FIX_ITERATIONS})...")
            critique = review(page, itinerary)
            if "no issues" in critique.lower() or "everything passes" in critique.lower():
                break
            progress("Taisomos peržiūroje rastos problemos...")
            itinerary = fix(itinerary, critique)
            stage_done("itinerary", itinerary)
            logistics_report = validate(itinerary)
            stage_done("logistics_report", logistics_report)
            page = run_page_designer({"itinerary": itinerary, "map_data": map_data, "images": images_for_page})
            stage_done("page", page)

    progress("Repozitorijos kūrimas ir puslapio publikavimas...")
    repo_name = _slugify(requirements)
    deploy_log = run_cicd(
        owner=os.environ.get("GITHUB_OWNER", "sauliusc"),
        repo_name=repo_name,
        description=f"{requirements.destination} trip page",
        page_html=page,
        images=images,
    )
    stage_done("deploy_log", deploy_log)
    print(deploy_log)
    return page


def run_travel_planner(user_requirements: str, on_progress=None, on_stage_complete=None) -> str:
    """Run the full pipeline for one trip request and return the final page HTML.

    Args:
        user_requirements: free-text trip request from the user
        on_progress: optional callable(str) invoked with a short status line
            before each agent stage -- each `claude -p` call inside a stage
            can itself take a while (real reasoning, real subscription
            usage), so without this the caller sees nothing at all between
            "started" and "finished", which looks identical to hung.
        on_stage_complete: optional callable(stage_name: str, output: str)
            invoked right after each stage produces its (string) output, so
            a caller can persist it for later inspection/rerun without
            re-running the whole pipeline.
    """
    return run_from_stage(
        "requirements",
        on_progress=on_progress,
        on_stage_complete=on_stage_complete,
        user_requirements=user_requirements,
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python orchestrator.py '<free-text trip requirements>'")
        sys.exit(1)
    run_travel_planner(sys.argv[1])
