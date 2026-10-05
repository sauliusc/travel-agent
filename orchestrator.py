"""Main orchestration flow: requirements -> research/weather -> accommodation ->
itinerary -> logistics validation -> map/images/budget -> page -> critic loop ->
CI/CD deploy.

All 14 agents from the design doc are wired in.
"""

import json
import os
import re

from agents.accommodation import find as run_accommodation
from agents.base import log_calls
from agents.budget import estimate as run_budget
from agents.car_rental import find as run_car_rental
from agents.cicd import deploy as run_cicd
from agents.cicd import page_url
from agents.critic import MAX_FIX_ITERATIONS, review
from agents.food import guide as run_food
from agents.packing import plan as run_packing
from agents.images import fetch_images as run_images
from agents.itinerary import fix, plan
from agents.logistics import validate
from agents.map_agent import build_map_data as run_map
from agents.page_designer import design as run_page_designer
from agents.requirements import analyze as run_requirements_analyst
from agents.research import research as run_research
from agents.weather import check as run_weather
from schemas.car_rental import CarRentalResults
from schemas.food import FoodGuide
from schemas.forecast import TripForecast
from schemas.packing import PackingList
from schemas.images import ImageResults
from schemas.logistics import LogisticsReport
from schemas.requirements import TripRequirements
from schemas.itinerary import Itinerary
from tools.image_download import download_images
from tools.forecast import trip_forecast
from tools.maps_links import day_routes
from tools.packing_html import inject as inject_packing

REPO_PREFIX = "ai-trip-"

# How many times the planner may rework the itinerary on Logistics Validator
# blockers before the run stops. An unresolved road/timing problem must never
# reach the page as a "warning" -- travellers can't act on uncertainty.
MAX_LOGISTICS_FIXES = 2


class LogisticsBlocked(RuntimeError):
    """The itinerary still has logistics blockers after MAX_LOGISTICS_FIXES reworks."""


def _blocker_text(report: LogisticsReport) -> str:
    return "\n".join(f"- {b.where}: {b.problem} -> {b.fix}" for b in report.blockers())


def _page_logistics(report: LogisticsReport) -> dict:
    # Traveller-facing facts only; `evidence` is internal.
    return {
        "legs": [leg.model_dump(exclude={"evidence", "confirmed"}) for leg in report.legs],
        "traveler_tips": report.traveler_tips,
    }

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
    "car_rental",
    "food",
    "forecast",
    "packing",
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
    on_llm_call=None,
    modification: str | None = None,
    user_requirements: str | None = None,
) -> str:
    """Run the pipeline starting at `stage_name`, reusing cached_outputs for
    everything before it, and continue through to CI/CD deploy. Returns the
    published page's URL.

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
        on_llm_call: see run_travel_planner
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
        with log_calls("requirements", on_llm_call):
            requirements = run_requirements_analyst(user_requirements)
        requirements_json = requirements.model_dump_json()
        stage_done("requirements", requirements_json)
    else:
        requirements_json = cached_outputs["requirements"]
        requirements = TripRequirements.model_validate_json(requirements_json)

    if reached("research"):
        progress("Tyrimas (kelionės objektai, keliai, sezoniškumas)...")
        with log_calls("research", on_llm_call):
            research = run_research(requirements_json)
        stage_done("research", research)
    else:
        research = cached_outputs["research"]

    if reached("weather"):
        progress("Orų/sezono patikra...")
        with log_calls("weather", on_llm_call):
            weather = run_weather(requirements_json)
        stage_done("weather", weather)
    else:
        weather = cached_outputs["weather"]

    if reached("accommodation"):
        progress("Nakvynės paieška...")
        with log_calls("accommodation", on_llm_call):
            accommodation = run_accommodation(f"requirements={requirements_json}\nresearch={research}")
        stage_done("accommodation", accommodation)
    else:
        accommodation = cached_outputs["accommodation"]

    if reached("itinerary"):
        if modification is not None and stage_name == "itinerary":
            progress("Dienų plano koregavimas pagal nurodymą...")
            with log_calls("itinerary", on_llm_call):
                itinerary = fix(cached_outputs["itinerary"], modification)
        else:
            progress("Dienų plano sudarymas...")
            with log_calls("itinerary", on_llm_call):
                itinerary = plan(
                    f"requirements={requirements_json}\nresearch={research}\n"
                    f"weather={weather}\naccommodation={accommodation}"
                )
        stage_done("itinerary", itinerary)
    else:
        itinerary = cached_outputs["itinerary"]

    def validate_until_ok(itinerary: str) -> tuple[str, LogisticsReport]:
        """Validate; on blockers let the planner rework the itinerary and
        re-validate, so only a fully confirmed itinerary moves on."""
        for attempt in range(MAX_LOGISTICS_FIXES + 1):
            progress("Logistikos patikra (važiavimo laikai, keliai)..." if attempt == 0
                     else f"Pakartotinė logistikos patikra ({attempt}/{MAX_LOGISTICS_FIXES})...")
            with log_calls("logistics_report", on_llm_call):
                report = validate(itinerary)
            stage_done("logistics_report", report.model_dump_json())
            if report.ok():
                return itinerary, report
            if attempt == MAX_LOGISTICS_FIXES:
                break
            progress(f"Logistika rado {len(report.blockers())} problemą(-as) -- dienų planas perdaromas...")
            with log_calls("itinerary", on_llm_call):
                itinerary = fix(itinerary, "Logistics Validator blockers:\n" + _blocker_text(report))
            stage_done("itinerary", itinerary)
        raise LogisticsBlocked(
            f"Logistika nepatvirtino maršruto po {MAX_LOGISTICS_FIXES} perdarymų:\n"
            f"{_blocker_text(report)}\nPakoreguok kelionę per „Pataisyti“ ir paleisk iš naujo."
        )

    if reached("logistics_report"):
        itinerary, logistics_report = validate_until_ok(itinerary)
    else:
        logistics_report = LogisticsReport.model_validate_json(cached_outputs["logistics_report"])
        if not logistics_report.ok():
            raise LogisticsBlocked(
                "Išsaugota logistikos ataskaita turi neišspręstų problemų -- paleisk nuo „Logistika“:\n"
                + _blocker_text(logistics_report)
            )

    if reached("map_data"):
        progress("Žemėlapio duomenų ruošimas...")
        with log_calls("map_data", on_llm_call):
            map_data = run_map(itinerary)
        stage_done("map_data", map_data)
    else:
        map_data = cached_outputs["map_data"]

    if reached("images"):
        progress("Nuotraukų paieška...")
        with log_calls("images", on_llm_call):
            picks = run_images(itinerary)
        progress("Nuotraukų atsisiuntimas ir licencijų patikra...")
        images = download_images(picks)
        if images.skipped:
            progress(f"Praleista nuotraukų: {len(images.skipped)} ({'; '.join(f'{k}: {v}' for k, v in images.skipped.items())})")
        stage_done("images", images.model_dump_json())
    else:
        images = ImageResults.model_validate_json(cached_outputs["images"])
    # run_page_designer's context gets json.dumps'd, which can't serialize a
    # Pydantic model directly -- pass the plain-dict form there, keep the
    # typed ImageResults for run_cicd (which needs .images/.license, not a dict).
    images_for_page = images.model_dump()

    if reached("car_rental"):
        progress("Automobilio nuomos pasiūlymai...")
        with log_calls("car_rental", on_llm_call):
            car_rental = run_car_rental(requirements_json, user_requirements or "")
        if not car_rental.needed:
            progress("Automobilio nuoma šiai kelionei nereikalinga -- praleidžiama.")
        stage_done("car_rental", car_rental.model_dump_json())
    else:
        car_rental = CarRentalResults.model_validate_json(cached_outputs["car_rental"])

    if reached("food"):
        progress("Maistas, vietiniai patiekalai ir barai...")
        with log_calls("food", on_llm_call):
            food = run_food(requirements_json, itinerary, accommodation)
        stage_done("food", food.model_dump_json())
    else:
        food = FoodGuide.model_validate_json(cached_outputs["food"])

    if reached("forecast"):
        progress("Orų prognozė...")
        forecast = trip_forecast(Itinerary.model_validate_json(itinerary), requirements.start_date)
        stage_done("forecast", forecast.model_dump_json())
    else:
        forecast = TripForecast.model_validate_json(cached_outputs["forecast"])

    if reached("packing"):
        progress("Daiktų sąrašas...")
        with log_calls("packing", on_llm_call):
            packing = run_packing(requirements_json, user_requirements or "", itinerary,
                                  forecast.model_dump_json(), car_rental.needed)
        stage_done("packing", packing.model_dump_json())
    else:
        packing = PackingList.model_validate_json(cached_outputs["packing"])

    # Stop photos and dish photos are shipped together.
    all_images = ImageResults(
        images=[*images.images, *(d.image for d in food.dishes if d.image)],
        skipped=images.skipped,
    )

    if reached("budget"):
        progress("Biudžeto skaičiavimas...")
        with log_calls("budget", on_llm_call):
            budget = run_budget({
                "itinerary": itinerary, "accommodation": accommodation,
                "car_rental": car_rental.model_dump(), "food": food.model_dump(exclude={"dishes": {"__all__": {"image"}}}),
            })
        stage_done("budget", budget)
    else:
        budget = cached_outputs["budget"]

    def page_context() -> dict:
        return {
            "language": requirements.language,
            "itinerary": itinerary,
            "day_routes": day_routes(Itinerary.model_validate_json(itinerary)),
            "logistics": _page_logistics(logistics_report),
            "budget": budget,
            "map_data": map_data,
            "images": images_for_page,
            "car_rental": car_rental.model_dump(),
            "food": food.model_dump(),
            "forecast": forecast.model_dump(),
            "packing": "rendered by code -- only place the <!-- PACKING_LIST --> placeholder",
        }

    repo_name = _slugify(requirements)

    def design_page() -> str:
        # The checklist (checkboxes + localStorage) is rendered by code, so it
        # works the same on every page regardless of the designer's markup.
        return inject_packing(run_page_designer(page_context()), packing, f"packing:{repo_name}")

    page_freshly_built = reached("page")
    if page_freshly_built:
        progress("Puslapio generavimas...")
        with log_calls("page", on_llm_call):
            page = design_page()
        stage_done("page", page)
    else:
        page = cached_outputs["page"]

    # Only worth re-critiquing a page we actually just (re)built -- if this
    # call only touches deploy_log, the cached page already passed review.
    if page_freshly_built:
        for attempt in range(MAX_FIX_ITERATIONS):
            progress(f"Peržiūra (bandymas {attempt + 1}/{MAX_FIX_ITERATIONS})...")
            with log_calls("critic", on_llm_call):
                critique = review(page, itinerary, logistics_report.model_dump_json(), all_images.model_dump_json(),
                                  json.dumps(page_context()["day_routes"], ensure_ascii=False))
            if "no issues" in critique.lower() or "everything passes" in critique.lower():
                break
            progress("Taisomos peržiūroje rastos problemos...")
            with log_calls("itinerary", on_llm_call):
                itinerary = fix(itinerary, critique)
            stage_done("itinerary", itinerary)
            itinerary, logistics_report = validate_until_ok(itinerary)
            with log_calls("page", on_llm_call):
                page = design_page()
            stage_done("page", page)

    progress("Repozitorijos kūrimas ir puslapio publikavimas...")
    owner = os.environ.get("GITHUB_OWNER", "sauliusc")
    deploy_log = run_cicd(
        owner=owner,
        repo_name=repo_name,
        description=f"{requirements.destination} trip page",
        page_html=page,
        images=all_images,
    )
    stage_done("deploy_log", deploy_log)
    print(deploy_log)
    return page_url(owner, repo_name)


def run_travel_planner(user_requirements: str, on_progress=None, on_stage_complete=None, on_llm_call=None) -> str:
    """Run the full pipeline for one trip request and return the published page's URL.

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
        on_llm_call: optional callable(stage_name: str, query: str,
            response: str) invoked after every real `claude -p` call
            (system prompt + input as `query`, raw CLI JSON as `response`)
            -- lets a caller persist the actual agent conversation for
            inspection, without needing to grep `ps aux`/journalctl on the
            machine the pipeline runs on.
    """
    return run_from_stage(
        "requirements",
        on_progress=on_progress,
        on_stage_complete=on_stage_complete,
        on_llm_call=on_llm_call,
        user_requirements=user_requirements,
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python orchestrator.py '<free-text trip requirements>'")
        sys.exit(1)
    run_travel_planner(sys.argv[1])
