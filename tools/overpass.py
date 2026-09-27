"""Road-type lookup near a point via the Overpass API (OpenStreetMap).

Used by the Logistics Validator agent to catch routes that pass through
unpaved 4x4-only tracks (highway=track) before they end up in an itinerary —
the exact mistake behind the SH74 (Osum -> Permet) route in the Albania trip.

Callable both as a Python function and as a CLI script, so the agent
(running under Claude Code) can invoke it via the Bash tool:
`python3 tools/overpass.py --lat .. --lon .. [--radius-m 50]`
"""

import argparse
import time

import httpx

# Multiple public Overpass instances, tried in order. overpass-api.de alone
# has been observed to intermittently reject requests (HTTP 406) on a real
# deployment even though the query itself is valid -- rather than surface
# that as an unverifiable route (which is exactly the SH74 failure mode
# this tool exists to prevent), fall back to the next mirror.
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]

# A descriptive User-Agent is Overpass API's documented etiquette
# requirement; requests without one are more likely to be rejected or
# deprioritized under load.
HEADERS = {"User-Agent": "travel-agent-logistics-validator/1.0 (https://github.com/sauliusc/travel-agent)"}

# Roads a standard rental car can use. If any of these is near the point,
# the car is on (or next to) a real road, whatever footpaths are also around --
# every town centre has footway/path/steps within 200m, and flagging those made
# nearly every urban stop a false "not passable" on a real run.
DRIVABLE_TAGS = {
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link",
    "unclassified", "residential", "living_street", "service",
}
# Car-width but unpaved/4x4 -- the SH74 case. Pedestrian-only ways
# (footway, path, steps, pedestrian, bridleway, cycleway) are ignored: a car
# never routes onto them, so they say nothing about the road it's on.
OFFROAD_TAGS = {"track"}

# A "drivable" road class can still be a gravel mountain road -- SH74-type
# roads are often mapped as secondary/unclassified with an unpaved surface,
# not as highway=track, so the surface/smoothness tags matter as much.
UNPAVED_SURFACES = {
    "unpaved", "gravel", "fine_gravel", "compacted", "dirt", "earth", "ground",
    "mud", "sand", "grass", "rock", "pebblestone", "woodchips",
}
BAD_SMOOTHNESS = {"bad", "very_bad", "horrible", "very_horrible", "impassable"}

# Small on purpose: sample points come from the route geometry, so the way the
# car is on is within a few metres. A large radius pulls in footpaths and
# side roads that say nothing about the road itself.
DEFAULT_RADIUS_M = 50


def _is_rough(tags: dict) -> bool:
    return tags.get("surface") in UNPAVED_SURFACES or tags.get("smoothness") in BAD_SMOOTHNESS

# Retry each mirror this many times (with backoff) before moving to the next,
# since Overpass instances can return transient 429/406/5xx under load.
RETRIES_PER_MIRROR = 2
BACKOFF_SECONDS = 2


def _query_mirror(url: str, query: str) -> httpx.Response:
    last_exc = None
    for attempt in range(RETRIES_PER_MIRROR):
        try:
            resp = httpx.post(url, data={"data": query}, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            last_exc = e
            if e.response.status_code not in (406, 429, 500, 502, 503, 504):
                raise  # not a transient/mirror-specific error, don't waste retries
            time.sleep(BACKOFF_SECONDS * (attempt + 1))
        except httpx.RequestError as e:
            last_exc = e
            time.sleep(BACKOFF_SECONDS * (attempt + 1))
    raise last_exc


def road_type(lat: float, lon: float, radius_m: int = DEFAULT_RADIUS_M) -> str:
    """Return the OSM highway type(s) found near a coordinate, flagging off-road tracks."""
    query = f"""
    [out:json][timeout:25];
    way(around:{radius_m},{lat},{lon})["highway"];
    out tags;
    """
    errors = []
    resp = None
    for url in OVERPASS_URLS:
        try:
            resp = _query_mirror(url, query)
            break
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            errors.append(f"{url}: {e}")
            continue

    if resp is None:
        # Every mirror failed -- report this as an explicit, unresolved check
        # rather than silently treating the road as safe. The Logistics
        # Validator's prompt already treats a missing road_type result as a
        # hard failure, which is the correct behavior here.
        joined = "; ".join(errors)
        return f"ERROR: could not reach any Overpass mirror to check this road ({joined})"

    elements = resp.json().get("elements", [])
    if not elements:
        return "No tagged road found near this point (may be off the mapped network)"

    ways = [el["tags"] for el in elements if "tags" in el]
    highway_types = sorted({t["highway"] for t in ways})
    all_types = ", ".join(highway_types)
    offroad = sorted({t["highway"] for t in ways if t["highway"] in OFFROAD_TAGS})
    paved = [t for t in ways if t["highway"] in DRIVABLE_TAGS and not _is_rough(t)]
    rough = [t for t in ways if t["highway"] in DRIVABLE_TAGS and _is_rough(t)]

    def describe(ts):
        return ", ".join(sorted({
            t["highway"] + (f" [surface={t['surface']}]" if "surface" in t else "")
            + (f" [smoothness={t['smoothness']}]" if "smoothness" in t else "")
            for t in ts
        }))

    if paved:
        note = ""
        if rough or offroad:
            note = f" (also nearby: {describe(rough) or ', '.join(offroad)} -- check which one the route uses)"
        return f"OK: paved drivable road here ({describe(paved)}){note}. All types nearby: {all_types}"
    if rough:
        return (
            f"WARNING: the only drivable road here is unpaved/rough ({describe(rough)}) -- "
            f"likely not suitable for a standard rental car. All types nearby: {all_types}"
        )
    if offroad:
        return (
            f"WARNING: only off-road track(s) here, no paved/drivable road within {radius_m}m — "
            f"not passable by a standard rental car. All types nearby: {all_types}"
        )
    return (
        f"WARNING: no car-drivable road within {radius_m}m (only: {all_types}) — "
        "check this point is reachable by car"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--radius-m", type=int, default=DEFAULT_RADIUS_M)
    args = parser.parse_args()
    print(road_type(args.lat, args.lon, args.radius_m))


if __name__ == "__main__":
    main()
