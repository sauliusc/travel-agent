"""Deterministic page checks run before the Review/Critic agent: things code
can verify exactly, so they never cost a review round (or an itinerary rework).
Every problem returned here is fixable by updating the page alone."""

import html
import re

_IMG_SRC = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.I)
_TAG = re.compile(r"<[^>]+>")


def _norm(text: str) -> str:
    text = html.unescape(_TAG.sub(" ", text))
    return re.sub(r"\s+", " ", text).strip().strip(".!").lower()


def check_page(page_html: str, image_paths: set[str], day_routes: list[dict], traveler_tips: list[str],
               booking_search: list[dict] | None = None, place_links: dict[str, str] | None = None,
               must_show: list[tuple[str, str]] | None = None) -> list[str]:
    """place_links: place name -> its Google Maps URL (stops, eateries, bars,
    places near the stays); every one must be linked from the page.
    must_show: (where, text) pairs whose text must appear on the page, e.g.
    each eatery's must-try dishes."""
    problems = []
    for src in sorted({s for s in _IMG_SRC.findall(page_html) if not s.startswith(("http:", "https:", "data:"))}):
        if src not in image_paths:
            problems.append(f"<img src=\"{src}\"> is not a verified image -- use exactly one of the "
                            f"`local_path` values from `images` / `food.dishes[].image`, or drop the photo")
    unescaped = html.unescape(page_html)
    for route in day_routes:
        for url in route["urls"]:
            if url not in unescaped:
                problems.append(f"Day {route['day']}: the day-route button must link exactly to {url}")
    for name, url in (place_links or {}).items():
        if url and url not in unescaped:
            problems.append(f"{name}: add a \"📍 Google Maps\" link to exactly {url}")
    for stay in booking_search or []:
        if stay["url"] not in unescaped:
            problems.append(f"Stay {stay['city']} {stay['checkin']}–{stay['checkout']}: add the Booking.com search "
                            f"button linking exactly to {stay['url']}")
    if "<!-- PACKING_LIST" not in page_html:
        problems.append("The <!-- PACKING_LIST --> placeholder is missing -- put it back in the packing section")
    if "<!-- TRIP_MAP" not in page_html:
        problems.append("The <!-- TRIP_MAP --> placeholder is missing -- put it in the map section")
    if "L.map(" in page_html.split("<!-- TRIP_MAP:START -->")[0] + page_html.split("<!-- TRIP_MAP:END -->")[-1]:
        problems.append("Remove the hand-written Leaflet map code -- the map is rendered by code at <!-- TRIP_MAP -->")
    text = _norm(page_html)
    for where, item in must_show or []:
        if _norm(item) not in text:
            problems.append(f"{where}: show \"{item}\"")
    for tip in traveler_tips:
        if _norm(tip) not in text:
            problems.append(f"Missing traveller tip (show it word for word): {tip}")
    return problems
