"""Road-type lookup near a point via the Overpass API (OpenStreetMap).

Used by the Logistics Validator agent to catch routes that pass through
unpaved 4x4-only tracks (highway=track) before they end up in an itinerary —
the exact mistake behind the SH74 (Osum -> Permet) route in the Albania trip.

Callable both as a Python function and as a CLI script, so the agent
(running under Claude Code) can invoke it via the Bash tool:
`python3 tools/overpass.py --lat .. --lon .. [--radius-m 200]`
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

# highway values that mean "not a standard rental car road"
OFFROAD_TAGS = {"track", "path", "bridleway", "footway"}

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


def road_type(lat: float, lon: float, radius_m: int = 200) -> str:
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

    highway_types = sorted({el["tags"]["highway"] for el in elements if "tags" in el})
    offroad = [h for h in highway_types if h in OFFROAD_TAGS]

    if offroad:
        return (
            f"WARNING: off-road segment(s) found ({', '.join(offroad)}) — "
            "not passable by a standard rental car. All types nearby: "
            f"{', '.join(highway_types)}"
        )
    return f"Road types nearby: {', '.join(highway_types)} (no off-road segments detected)"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--radius-m", type=int, default=200)
    args = parser.parse_args()
    print(road_type(args.lat, args.lon, args.radius_m))


if __name__ == "__main__":
    main()
