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


def check_page(page_html: str, image_paths: set[str], day_routes: list[dict], traveler_tips: list[str]) -> list[str]:
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
    if "<!-- PACKING_LIST" not in page_html:
        problems.append("The <!-- PACKING_LIST --> placeholder is missing -- put it back in the packing section")
    if "<!-- TRIP_MAP" not in page_html:
        problems.append("The <!-- TRIP_MAP --> placeholder is missing -- put it in the map section")
    if "L.map(" in page_html.split("<!-- TRIP_MAP:START -->")[0] + page_html.split("<!-- TRIP_MAP:END -->")[-1]:
        problems.append("Remove the hand-written Leaflet map code -- the map is rendered by code at <!-- TRIP_MAP -->")
    text = _norm(page_html)
    for tip in traveler_tips:
        if _norm(tip) not in text:
            problems.append(f"Missing traveller tip (show it word for word): {tip}")
    return problems
