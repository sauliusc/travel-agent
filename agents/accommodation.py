"""Accommodation agent: finds lodging options per overnight city via web search."""

from pathlib import Path

from agents.base import run_agent

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "accommodation.md").read_text()


def find(context_json: str) -> str:
    """Find 2-3 accommodation options per overnight city.

    Args:
        context_json: JSON combining TripRequirements and the Research agent's
            candidate overnight cities (or the itinerary's overnight_city fields,
            once the itinerary exists)
    """
    return run_agent(SYSTEM_PROMPT, ["WebSearch"], context_json)
