"""Map agent: turns a finalized Itinerary into Leaflet.js-ready map data."""

from pathlib import Path

from agents.base import run_agent

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "map.md").read_text()


def build_map_data(itinerary_json: str) -> str:
    """Produce Leaflet.js points/polyline data for the Page Designer to embed.

    Args:
        itinerary_json: JSON-serialized Itinerary (see schemas/itinerary.py)
    """
    # No tools of its own — coordinates already live on the Itinerary's Stop objects.
    return run_agent(SYSTEM_PROMPT, [], itinerary_json)
