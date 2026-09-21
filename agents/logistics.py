"""Logistics Validator agent: checks every itinerary leg against real road data."""

from pathlib import Path

from agents.base import run_agent
from tools.osrm import driving_time
from tools.overpass import road_type

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "logistics.md").read_text()


def validate(itinerary_json: str) -> str:
    """Validate an itinerary's driving legs and flag off-road/overloaded days.

    Args:
        itinerary_json: JSON-serialized Itinerary (see schemas/itinerary.py)
    """
    return run_agent(SYSTEM_PROMPT, [driving_time, road_type], itinerary_json)
