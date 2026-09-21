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


def run_travel_planner(user_requirements: str) -> str:
    """Run the full pipeline for one trip request and return the final page HTML.

    Args:
        user_requirements: free-text trip request from the user
    """
    requirements = run_requirements_analyst(user_requirements)
    requirements_json = requirements.model_dump_json()
    research = run_research(requirements_json)
    weather = run_weather(requirements_json)
    accommodation = run_accommodation(f"requirements={requirements_json}\nresearch={research}")

    itinerary = plan(
        f"requirements={requirements_json}\nresearch={research}\n"
        f"weather={weather}\naccommodation={accommodation}"
    )
    logistics_report = validate(itinerary)

    map_data = run_map(itinerary)
    images = run_images(itinerary)
    budget = run_budget({"itinerary": itinerary, "accommodation": accommodation})

    page = run_page_designer({"itinerary": itinerary, "map_data": map_data, "images": images})

    for _ in range(MAX_FIX_ITERATIONS):
        critique = review(page, itinerary)
        if "no issues" in critique.lower() or "everything passes" in critique.lower():
            break
        itinerary = fix(itinerary, critique)
        logistics_report = validate(itinerary)
        page = run_page_designer({"itinerary": itinerary, "map_data": map_data, "images": images})

    repo_name = _slugify(requirements)
    deploy_log = run_cicd(
        owner=os.environ.get("GITHUB_OWNER", "sauliusc"),
        repo_name=repo_name,
        description=f"{requirements.destination} trip page",
        page_html=page,
        images_summary=images,
    )
    print(deploy_log)
    return page


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python orchestrator.py '<free-text trip requirements>'")
        sys.exit(1)
    run_travel_planner(sys.argv[1])
