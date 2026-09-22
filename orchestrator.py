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


def run_travel_planner(user_requirements: str, on_progress=None) -> str:
    """Run the full pipeline for one trip request and return the final page HTML.

    Args:
        user_requirements: free-text trip request from the user
        on_progress: optional callable(str) invoked with a short status line
            before each agent stage -- each `claude -p` call inside a stage
            can itself take a while (real reasoning, real subscription
            usage), so without this the caller sees nothing at all between
            "started" and "finished", which looks identical to hung.
    """
    progress = on_progress or (lambda _msg: None)

    progress("Reikalavimų analizė...")
    requirements = run_requirements_analyst(user_requirements)
    requirements_json = requirements.model_dump_json()

    progress("Tyrimas (kelionės objektai, keliai, sezoniškumas)...")
    research = run_research(requirements_json)

    progress("Orų/sezono patikra...")
    weather = run_weather(requirements_json)

    progress("Nakvynės paieška...")
    accommodation = run_accommodation(f"requirements={requirements_json}\nresearch={research}")

    progress("Dienų plano sudarymas...")
    itinerary = plan(
        f"requirements={requirements_json}\nresearch={research}\n"
        f"weather={weather}\naccommodation={accommodation}"
    )

    progress("Logistikos patikra (važiavimo laikai, keliai)...")
    logistics_report = validate(itinerary)

    progress("Žemėlapio duomenų ruošimas...")
    map_data = run_map(itinerary)

    progress("Nuotraukų paieška...")
    images = run_images(itinerary)
    # run_page_designer's context gets json.dumps'd, which can't serialize a
    # Pydantic model directly -- pass the plain-dict form there, keep the
    # typed ImageResults for run_cicd (which needs .images/.license, not a dict).
    images_for_page = images.model_dump()

    progress("Biudžeto skaičiavimas...")
    budget = run_budget({"itinerary": itinerary, "accommodation": accommodation})

    progress("Puslapio generavimas...")
    page = run_page_designer({"itinerary": itinerary, "map_data": map_data, "images": images_for_page})

    for attempt in range(MAX_FIX_ITERATIONS):
        progress(f"Peržiūra (bandymas {attempt + 1}/{MAX_FIX_ITERATIONS})...")
        critique = review(page, itinerary)
        if "no issues" in critique.lower() or "everything passes" in critique.lower():
            break
        progress("Taisomos peržiūroje rastos problemos...")
        itinerary = fix(itinerary, critique)
        logistics_report = validate(itinerary)
        page = run_page_designer({"itinerary": itinerary, "map_data": map_data, "images": images_for_page})

    progress("Repozitorijos kūrimas ir puslapio publikavimas...")
    repo_name = _slugify(requirements)
    deploy_log = run_cicd(
        owner=os.environ.get("GITHUB_OWNER", "sauliusc"),
        repo_name=repo_name,
        description=f"{requirements.destination} trip page",
        page_html=page,
        images=images,
    )
    print(deploy_log)
    return page


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python orchestrator.py '<free-text trip requirements>'")
        sys.exit(1)
    run_travel_planner(sys.argv[1])
