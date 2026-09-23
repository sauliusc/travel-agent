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

REPO_PREFIX = "ai-trip-"


def _slugify(requirements) -> str:
    base = f"{requirements.destination}-{requirements.trip_type}"
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    return f"{REPO_PREFIX}{slug}"


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
    progress = on_progress or (lambda _msg: None)
    stage_done = on_stage_complete or (lambda _stage, _output: None)

    progress("Reikalavimų analizė...")
    requirements = run_requirements_analyst(user_requirements)
    requirements_json = requirements.model_dump_json()
    stage_done("requirements", requirements_json)

    progress("Tyrimas (kelionės objektai, keliai, sezoniškumas)...")
    research = run_research(requirements_json)
    stage_done("research", research)

    progress("Orų/sezono patikra...")
    weather = run_weather(requirements_json)
    stage_done("weather", weather)

    progress("Nakvynės paieška...")
    accommodation = run_accommodation(f"requirements={requirements_json}\nresearch={research}")
    stage_done("accommodation", accommodation)

    progress("Dienų plano sudarymas...")
    itinerary = plan(
        f"requirements={requirements_json}\nresearch={research}\n"
        f"weather={weather}\naccommodation={accommodation}"
    )
    stage_done("itinerary", itinerary)

    progress("Logistikos patikra (važiavimo laikai, keliai)...")
    logistics_report = validate(itinerary)
    stage_done("logistics_report", logistics_report)

    progress("Žemėlapio duomenų ruošimas...")
    map_data = run_map(itinerary)
    stage_done("map_data", map_data)

    progress("Nuotraukų paieška...")
    images = run_images(itinerary)
    # run_page_designer's context gets json.dumps'd, which can't serialize a
    # Pydantic model directly -- pass the plain-dict form there, keep the
    # typed ImageResults for run_cicd (which needs .images/.license, not a dict).
    images_for_page = images.model_dump()
    stage_done("images", images.model_dump_json())

    progress("Biudžeto skaičiavimas...")
    budget = run_budget({"itinerary": itinerary, "accommodation": accommodation})
    stage_done("budget", budget)

    progress("Puslapio generavimas...")
    page = run_page_designer({"itinerary": itinerary, "map_data": map_data, "images": images_for_page})
    stage_done("page", page)

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


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python orchestrator.py '<free-text trip requirements>'")
        sys.exit(1)
    run_travel_planner(sys.argv[1])
