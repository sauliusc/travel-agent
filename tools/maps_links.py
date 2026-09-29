"""Google Maps driving-directions links for each itinerary day, built
deterministically from the stops' coordinates (not by an LLM, so the link
always matches the validated plan).

Uses the documented Maps URLs format:
https://www.google.com/maps/dir/?api=1&origin=..&destination=..&waypoints=..&travelmode=driving
"""

from urllib.parse import urlencode, quote

from schemas.itinerary import Itinerary

# Maps URLs accept at most 9 waypoints; longer days are split into parts that
# share their boundary stop (part 2 starts where part 1 ends).
MAX_WAYPOINTS = 9
MAX_STOPS_PER_LINK = MAX_WAYPOINTS + 2

BASE = "https://www.google.com/maps/dir/?"


def _point(stop) -> str:
    return f"{stop.lat:.6f},{stop.lon:.6f}"


def directions_url(points: list[str]) -> str:
    params = {"api": "1", "origin": points[0], "destination": points[-1], "travelmode": "driving"}
    if len(points) > 2:
        params["waypoints"] = "|".join(points[1:-1])
    return BASE + urlencode(params, safe=",|")


def day_routes(itinerary: Itinerary) -> list[dict]:
    """Per day: {"day", "title", "urls"} -- one URL, or several parts for a day
    with more stops than one link allows. Days with fewer than 2 distinct
    places (e.g. arrival straight to an airport hotel) get no URLs."""
    routes = []
    for day in itinerary.days:
        points: list[str] = []
        for stop in day.stops:
            p = _point(stop)
            if not points or points[-1] != p:  # skip consecutive stops at the same spot
                points.append(p)
        urls = []
        if len(points) >= 2:
            step = MAX_STOPS_PER_LINK - 1
            for start in range(0, len(points) - 1, step):
                urls.append(directions_url(points[start:start + MAX_STOPS_PER_LINK]))
        routes.append({"day": day.number, "title": day.title, "urls": urls})
    return routes


def place_search_url(name: str, city: str) -> str:
    """Google Maps search link for a named place (restaurant, bar) in a city."""
    return "https://www.google.com/maps/search/?api=1&query=" + quote(f"{name}, {city}")
