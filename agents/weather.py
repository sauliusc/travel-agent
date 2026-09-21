"""Weather & Season agent: checks seasonal fit for the destination and dates."""

from pathlib import Path

from agents.base import run_agent
from tools.open_meteo import climate_summary

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "weather.md").read_text()

SERVER_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 5},
]


def check(requirements_json: str) -> str:
    """Check seasonal fit (temperature, rain, road-access issues) for the trip dates.

    Args:
        requirements_json: JSON-serialized TripRequirements
    """
    return run_agent(SYSTEM_PROMPT, [climate_summary, *SERVER_TOOLS], requirements_json)
