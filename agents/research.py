"""Research agent: gathers route/logistics/seasonal info via Claude Code's
built-in WebSearch and WebFetch tools.
"""

from pathlib import Path

from agents.base import run_agent

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "research.md").read_text()


def research(requirements_json: str) -> str:
    """Research candidate stops, road warnings, and seasonal notes for a destination.

    Args:
        requirements_json: JSON-serialized TripRequirements
    """
    return run_agent(SYSTEM_PROMPT, ["WebSearch", "WebFetch"], requirements_json)
