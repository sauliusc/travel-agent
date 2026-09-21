"""Review/Critic agent: last check before a page ships.

Exists because a manually planned trip once shipped with a route through an
unmarked 4x4-only track (SH74) — this agent's job is to make sure that
mistake, and its relatives, never reach a generated page again.
"""

from pathlib import Path

from agents.base import run_agent

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "critic.md").read_text()

MAX_FIX_ITERATIONS = 3


def review(page_html: str, itinerary_json: str) -> str:
    """Review a generated page and itinerary for logistics/consistency errors.

    Args:
        page_html: the generated index.html content
        itinerary_json: the Itinerary the page was built from
    """
    task = f"Page HTML:\n{page_html}\n\nItinerary:\n{itinerary_json}"
    return run_agent(SYSTEM_PROMPT, [], task)
