"""Page Designer agent: generates the final single-file index.html trip page."""

import json
from pathlib import Path

from agents.base import run_agent

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "page_designer.md").read_text()

# Full-page HTML generation can run long -- give the subprocess more time
# than the 600s default used by shorter agent turns.
TIMEOUT = 900


def design(context: dict) -> str:
    """Generate the complete index.html for a trip.

    Args:
        context: dict with keys "itinerary", "map_data", "images" (all as produced
            by the corresponding upstream agents)
    """
    task = json.dumps(context, ensure_ascii=False)
    return run_agent(SYSTEM_PROMPT, [], task, timeout=TIMEOUT)
