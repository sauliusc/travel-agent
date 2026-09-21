"""Image agent: finds a Wikimedia Commons photo for every stop in the itinerary."""

from pathlib import Path

from agents.base import run_agent
from tools.wikimedia import find_image

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "images.md").read_text()


def fetch_images(itinerary_json: str) -> str:
    """Find a licensed Wikimedia Commons image for every stop in the itinerary.

    Args:
        itinerary_json: JSON-serialized Itinerary (see schemas/itinerary.py)
    """
    return run_agent(SYSTEM_PROMPT, [find_image], itinerary_json)
