"""Budget agent: estimates a min/likely/max cost breakdown for the trip."""

import json
from pathlib import Path

from agents.base import run_agent

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "budget.md").read_text()


def estimate(context: dict) -> str:
    """Estimate a cost breakdown (flights, car, lodging, food, tickets, fuel).

    Args:
        context: dict with keys "itinerary" and "accommodation" (as produced by
            the Itinerary Planner and Accommodation agents)
    """
    task = json.dumps(context, ensure_ascii=False)
    return run_agent(SYSTEM_PROMPT, ["WebSearch"], task)
