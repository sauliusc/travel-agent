"""Accommodation agent: finds lodging options per overnight city via web_search."""

from pathlib import Path

from agents.base import run_agent

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "accommodation.md").read_text()

SERVER_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 10},
]


def find(context_json: str) -> str:
    """Find 2-3 accommodation options per overnight city.

    Args:
        context_json: JSON combining TripRequirements and the Research agent's
            candidate overnight cities (or the itinerary's overnight_city fields,
            once the itinerary exists)
    """
    return run_agent(SYSTEM_PROMPT, SERVER_TOOLS, context_json)
