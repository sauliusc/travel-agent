"""Image agent: finds a Wikimedia Commons photo for every stop in the itinerary."""

from pathlib import Path

from agents.base import run_agent

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "images.md").read_text()

TOOL_HINT = (
    'Use Bash to look up each stop: `python3 tools/wikimedia.py --query "<place name>"`.'
)


def fetch_images(itinerary_json: str) -> str:
    """Find a licensed Wikimedia Commons image for every stop in the itinerary.

    Args:
        itinerary_json: JSON-serialized Itinerary (see schemas/itinerary.py)
    """
    task = f"{itinerary_json}\n\n{TOOL_HINT}"
    return run_agent(SYSTEM_PROMPT, ["Bash"], task)
