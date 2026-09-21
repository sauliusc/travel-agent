"""Main orchestration flow: requirements -> research -> logistics -> itinerary ->
map/images/budget -> page -> critic -> CI/CD.

Runnable agents (logistics, itinerary, critic) are wired in; agents not yet
implemented (requirements, research, accommodation, map, images, page_designer,
budget, weather, docs, cicd) are TODO stubs that raise NotImplementedError so a
partial run fails loudly instead of silently producing a broken page.
"""

from agents.critic import MAX_FIX_ITERATIONS, review
from agents.itinerary import fix, plan
from agents.logistics import validate
from agents.accommodation import find as run_accommodation
from agents.images import fetch_images as run_images
from agents.map_agent import build_map_data as run_map
from agents.requirements import analyze as run_requirements_analyst
from agents.research import research as run_research


def _not_implemented(name: str):
    def stub(*_args, **_kwargs):
        raise NotImplementedError(f"{name} agent is not implemented yet (see GitHub issues)")

    return stub

run_page_designer = _not_implemented("Page Designer")
run_budget = _not_implemented("Budget")
run_weather = _not_implemented("Weather")
run_cicd = _not_implemented("CI/CD")


def run_travel_planner(user_requirements: str) -> str:
    """Run the full pipeline for one trip request and return the final page HTML.

    Args:
        user_requirements: free-text trip request from the user
    """
    requirements = run_requirements_analyst(user_requirements)
    requirements_json = requirements.model_dump_json()
    research = run_research(requirements_json)
    accommodation = run_accommodation(f"requirements={requirements_json}\nresearch={research}")

    itinerary = plan(f"requirements={requirements_json}\nresearch={research}\naccommodation={accommodation}")
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

    run_cicd(page)
    return page


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python orchestrator.py '<free-text trip requirements>'")
        sys.exit(1)
    run_travel_planner(sys.argv[1])
