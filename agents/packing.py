"""Packing Planner agent: what to take, from the itinerary, forecast and baggage."""

import json
from pathlib import Path

from agents.base import run_structured
from schemas.packing import PackingList

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "packing.md").read_text()


def plan(requirements_json: str, user_request: str, itinerary_json: str, forecast_json: str, car_rental_needed: bool) -> PackingList:
    task = (
        f"Trip requirements:\n{requirements_json}\n\nOriginal request:\n{user_request}\n\n"
        f"Itinerary:\n{itinerary_json}\n\nForecast:\n{forecast_json}\n\n"
        f"Rental car: {json.dumps(car_rental_needed)}"
    )
    return run_structured(SYSTEM_PROMPT, [], task, PackingList, timeout=600,
                          disallowed_tools=["Bash", "WebSearch", "WebFetch"])
