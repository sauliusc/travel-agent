"""Logistics Validator agent: checks every itinerary leg against real road data."""

from pathlib import Path

from agents.base import run_agent

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "logistics.md").read_text()

TOOL_HINT = (
    "Use Bash to check each leg: `python3 tools/osrm.py --from-lat .. --from-lon .. "
    "--to-lat .. --to-lon ..` for driving distance/time, and "
    "`python3 tools/overpass.py --lat .. --lon ..` to flag off-road segments."
)


def validate(itinerary_json: str) -> str:
    """Validate an itinerary's driving legs and flag off-road/overloaded days.

    Args:
        itinerary_json: JSON-serialized Itinerary (see schemas/itinerary.py)
    """
    task = f"{itinerary_json}\n\n{TOOL_HINT}"
    return run_agent(SYSTEM_PROMPT, ["Bash"], task)
