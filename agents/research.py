"""Research agent: gathers route/logistics/seasonal info via Anthropic's
server-hosted web_search and web_fetch tools (no client-side tool code).
"""

from pathlib import Path

from agents.base import run_agent

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "research.md").read_text()

# Server tools run on Anthropic's infrastructure; no local execution needed.
SERVER_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 15},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 10},
]


def research(requirements_json: str) -> str:
    """Research candidate stops, road warnings, and seasonal notes for a destination.

    Args:
        requirements_json: JSON-serialized TripRequirements
    """
    return run_agent(SYSTEM_PROMPT, SERVER_TOOLS, requirements_json)
