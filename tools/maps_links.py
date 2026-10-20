"""Google Maps links for itinerary days and places, built deterministically
by code (not by an LLM, so a link always matches the validated plan).

Places are given to Google Maps by name (`Stop.maps_query`: name + town, or
the street address when the name is ambiguous), so the route shows "Berat
Castle" rather than "40.708,19.946". A stop without a query falls back to
its coordinates.

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


SEARCH = "https://www.google.com/maps/search/?api=1&query="


def _coords(stop) -> str:
    return f"{stop.lat:.6f},{stop.lon:.6f}"


def _point(stop) -> str:
    # "|" separates waypoints, so a query containing it can't be used.
    query = " ".join((getattr(stop, "maps_query", "") or "").replace("|", " ").split())
    return query or _coords(stop)


def directions_url(points: list[str]) -> str:
    params = {"api": "1", "origin": points[0], "destination": points[-1], "travelmode": "driving"}
    if len(points) > 2:
        params["waypoints"] = "|".join(points[1:-1])
    return BASE + urlencode(params, safe=",|")


def stop_url(stop) -> str:
    """Google Maps link to a single stop: by name/address, else by coordinates."""
    return SEARCH + quote(_point(stop))


def with_place_urls(itinerary: Itinerary) -> Itinerary:
    """Set every stop's google_maps_url from its maps_query / coordinates."""
    for day in itinerary.days:
        for stop in day.stops:
            stop.google_maps_url = stop_url(stop)
    return itinerary


def day_routes(itinerary: Itinerary) -> list[dict]:
    """Per day: {"day", "title", "urls"} -- one URL, or several parts for a day
    with more stops than one link allows. Days with fewer than 2 distinct
    places (e.g. arrival straight to an airport hotel) get no URLs."""
    routes = []
    for day in itinerary.days:
        points: list[str] = []
        last = None
        for stop in day.stops:
            p, here = _point(stop), _coords(stop)
            if last != here and (not points or points[-1] != p):  # skip consecutive stops at the same spot
                points.append(p)
            last = here
        urls = []
        if len(points) >= 2:
            step = MAX_STOPS_PER_LINK - 1
            for start in range(0, len(points) - 1, step):
                urls.append(directions_url(points[start:start + MAX_STOPS_PER_LINK]))
        routes.append({"day": day.number, "title": day.title, "urls": urls})
    return routes


def place_search_url(name: str, city: str, address: str = "") -> str:
    """Google Maps search link for a named place (restaurant, bar): name plus
    street address when known (tells apart same-named places), else the city."""
    return SEARCH + quote(f"{name}, {address.strip() or city}")
