"""Review/Critic agent: last check before a page ships.

Exists because a manually planned trip once shipped with a route through an
unmarked 4x4-only track (SH74) — this agent's job is to make sure that
mistake, and its relatives, never reach a generated page again.
"""

from pathlib import Path

from agents.base import run_agent

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "critic.md").read_text()

MAX_FIX_ITERATIONS = 3


def review(page_html: str, itinerary_json: str, logistics_report_json: str, images_manifest_json: str, day_routes_json: str) -> str:
    """Review a generated page and itinerary for logistics/consistency errors.

    Args:
        page_html: the generated index.html content
        itinerary_json: the Itinerary the page was built from
        logistics_report_json: the passed LogisticsReport (schemas/logistics.py)
        images_manifest_json: verified ImageResults from tools/image_download.py
        day_routes_json: per-day Google Maps route URLs (tools/maps_links.py)
    """
    task = (
        f"Page HTML:\n{page_html}\n\nItinerary:\n{itinerary_json}\n\n"
        f"Logistics report (already passed validation):\n{logistics_report_json}\n\n"
        f"Verified image manifest:\n{images_manifest_json}\n\n"
        f"Day route links (day_routes):\n{day_routes_json}"
    )
    return run_agent(SYSTEM_PROMPT, [], task)
