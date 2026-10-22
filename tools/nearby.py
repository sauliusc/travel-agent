"""Nearest places to eat and shops around each overnight place, from
OpenStreetMap (Overpass), with the distance computed by code.

The overnight places are the last stop of every night's day in the itinerary
(consecutive nights at the same place are one entry). Distances are walking
estimates from the straight line (paths wind ~30% more), not an LLM's guess.

CLI (smoke test): `python3 tools/nearby.py --lat 40.7058 --lon 19.9522`
"""

import argparse
import json
import math
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent.parent))  # so the CLI form can import tools/

from tools.maps_links import SEARCH
from tools.overpass import _post

EATERIES = 5
SHOPS = 3
# Searched in widening circles until enough places are found (rural stays).
RADII_M = (1000, 3000)
SAME_PLACE_KM = 0.3
WALK_DETOUR, WALK_KMH = 1.3, 4.5

EAT = "restaurant|cafe|fast_food|pub|food_court|biergarten"
SHOP = "supermarket|convenience|grocery|greengrocer|general|deli"


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    kx = 111.32 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lon1 - lon2) * kx, (lat1 - lat2) * 110.54)


def _query(lat: float, lon: float, radius_m: int) -> str:
    around = f"(around:{radius_m},{lat},{lon})"
    return (f'[out:json][timeout:40];(nwr{around}["amenity"~"^({EAT})$"]["name"];'
            f'nwr{around}["shop"~"^({SHOP})$"]["name"];);out center tags;')


def _place(el: dict, lat: float, lon: float, city: str) -> dict:
    tags = el.get("tags", {})
    plat = el.get("lat", el.get("center", {}).get("lat"))
    plon = el.get("lon", el.get("center", {}).get("lon"))
    km = _km(lat, lon, plat, plon) * WALK_DETOUR
    street = " ".join(filter(None, [tags.get("addr:street"), tags.get("addr:housenumber")]))
    where = ", ".join(filter(None, [street, tags.get("addr:city") or city]))
    return {
        "name": tags["name"],
        "kind": tags.get("amenity") or tags.get("shop"),
        "cuisine": tags.get("cuisine", "").replace(";", ", ") or None,
        "opening_hours": tags.get("opening_hours"),
        "distance_m": int(round(km * 1000, -1)),
        "walk_min": max(1, round(km / WALK_KMH * 60)),
        "maps_url": SEARCH + quote(f"{tags['name']}, {where}" if where else f"{tags['name']} {plat:.5f},{plon:.5f}"),
    }


def around(lat: float, lon: float, city: str = "", post=_post) -> dict:
    """{"eateries": nearest EATERIES places to eat, "shops": nearest SHOPS
    food shops}, each sorted by distance."""
    eat, shops = [], []
    for radius in RADII_M:
        elements = post(_query(lat, lon, radius)).get("elements", [])
        places = [(el, _place(el, lat, lon, city)) for el in elements
                  if el.get("tags", {}).get("name") and (el.get("lat") or el.get("center"))]
        eat = sorted((p for el, p in places if "amenity" in el["tags"]), key=lambda p: p["distance_m"])
        shops = sorted((p for el, p in places if "shop" in el["tags"]), key=lambda p: p["distance_m"])
        if len(eat) >= EATERIES and len(shops) >= SHOPS:
            break
    return {"eateries": _nearest_unique(eat, EATERIES), "shops": _nearest_unique(shops, SHOPS)}


def _nearest_unique(places: list[dict], n: int) -> list[dict]:
    """First n by distance, one per name (a place mapped as both node and building)."""
    seen, out = set(), []
    for p in places:
        if p["name"] not in seen:
            seen.add(p["name"])
            out.append(p)
    return out[:n]


def overnight_places(itinerary) -> list[dict]:
    """Where the travellers sleep: the last stop of each day except the last
    (that night is spent at home), consecutive nights at one place merged."""
    places: list[dict] = []
    for day in itinerary.days[:-1]:
        if not day.stops:
            continue
        stop = day.stops[-1]
        if places and _km(places[-1]["lat"], places[-1]["lon"], stop.lat, stop.lon) < SAME_PLACE_KM:
            places[-1]["nights"].append(day.number)
            continue
        places.append({"name": stop.name, "city": day.overnight_city, "lat": stop.lat, "lon": stop.lon,
                       "nights": [day.number]})
    return places


def nearby_for_stays(itinerary, post=_post) -> list[dict]:
    """Per overnight place: name, city, nights (day numbers), eateries, shops.
    A lookup failure leaves that place's lists empty with an `error`."""
    out = []
    for place in overnight_places(itinerary):
        try:
            found = around(place["lat"], place["lon"], place["city"], post)
        except Exception as e:  # noqa: BLE001 - map data outage: report, don't fail the trip
            found = {"eateries": [], "shops": [], "error": str(e)}
        out.append({**place, **found})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--city", default="")
    args = parser.parse_args()
    print(json.dumps(around(args.lat, args.lon, args.city), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
