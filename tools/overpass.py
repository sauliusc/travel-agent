"""Road-type lookup near a point via the Overpass API (OpenStreetMap).

Used by the Logistics Validator agent to catch routes that pass through
unpaved 4x4-only tracks (highway=track) before they end up in an itinerary —
the exact mistake behind the SH74 (Osum -> Permet) route in the Albania trip.

Callable both as a Python function and as a CLI script, so the agent
(running under Claude Code) can invoke it via the Bash tool:
`python3 tools/overpass.py --lat .. --lon .. [--radius-m 50]`
"""

import argparse
import math
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


# Overall budget per Overpass request across all mirrors and retries. Without
# it, 3 mirrors x 2 retries x 30s could run past the agent's 120s Bash limit on
# a single point (seen on a real run, where the Logistics Validator then timed
# out at 1200s).
DEADLINE_SECONDS = 90


def _post(query: str) -> dict:
    """Run a query against the mirrors in order; raise RuntimeError listing every failure."""
    errors = []
    started = time.monotonic()
    for url in OVERPASS_URLS:
        for attempt in range(RETRIES_PER_MIRROR):
            remaining = DEADLINE_SECONDS - (time.monotonic() - started)
            if remaining <= 5:
                errors.append("overall deadline reached")
                raise RuntimeError("; ".join(errors))
            try:
                resp = httpx.post(url, data={"data": query}, headers=HEADERS, timeout=min(45, remaining))
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                errors.append(f"{url}: HTTP {e.response.status_code}")
                if e.response.status_code not in (406, 429, 500, 502, 503, 504):
                    break  # not transient -- next mirror
            except httpx.RequestError as e:
                errors.append(f"{url}: {type(e).__name__}")
            time.sleep(BACKOFF_SECONDS * (attempt + 1))
    raise RuntimeError("; ".join(errors))


def classify(ways: list[dict], radius_m: int) -> str:
    """OK/WARNING verdict for the highway-tagged ways found at one point."""
    if not ways:
        return "WARNING: no mapped road at this point -- check it is reachable by car"
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
        return f"OK: paved drivable road here ({describe(paved)}){note}"
    if rough:
        return (
            f"WARNING: the only drivable road here is unpaved/rough ({describe(rough)}) -- "
            "likely not suitable for a standard rental car"
        )
    if offroad:
        return (
            f"WARNING: only off-road track(s) here, no paved/drivable road within {radius_m}m -- "
            f"not passable by a standard rental car (nearby: {all_types})"
        )
    return f"WARNING: no car-drivable road within {radius_m}m (only: {all_types}) -- check this point is reachable by car"


def _dist_to_way(lat: float, lon: float, geom: list[dict]) -> float:
    """Approximate distance (m) from a point to a way's polyline (equirectangular)."""
    kx = 111_320 * math.cos(math.radians(lat))
    ky = 110_540
    best = float("inf")
    pts = [((g["lon"] - lon) * kx, (g["lat"] - lat) * ky) for g in geom]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] or pts):
        dx, dy = x2 - x1, y2 - y1
        seg = dx * dx + dy * dy
        t = 0.0 if seg == 0 else max(0.0, min(1.0, -(x1 * dx + y1 * dy) / seg))
        best = min(best, math.hypot(x1 + t * dx, y1 + t * dy))
    return best


def road_types(points: list[tuple[float, float]], radius_m: int = DEFAULT_RADIUS_M) -> list[str]:
    """Classify many points with ONE Overpass request (sequential single-point
    calls in parallel got rate-limited on a real run). Ways are assigned to
    points by distance to their geometry."""
    parts = "".join(f'way(around:{radius_m},{lat},{lon})["highway"];' for lat, lon in points)
    try:
        data = _post(f"[out:json][timeout:60];({parts});out tags geom;")
    except RuntimeError as e:
        # Explicit, unresolved check -- never silently treat the road as safe.
        return [f"ERROR: could not reach any Overpass mirror ({e})"] * len(points)
    ways = [el for el in data.get("elements", []) if "tags" in el and "geometry" in el]
    return [
        classify([w["tags"] for w in ways if _dist_to_way(lat, lon, w["geometry"]) <= radius_m], radius_m)
        for lat, lon in points
    ]


def road_type(lat: float, lon: float, radius_m: int = DEFAULT_RADIUS_M) -> str:
    """Classify the road at a single coordinate."""
    return road_types([(lat, lon)], radius_m)[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--radius-m", type=int, default=DEFAULT_RADIUS_M)
    args = parser.parse_args()
    print(road_type(args.lat, args.lon, args.radius_m))


if __name__ == "__main__":
    main()
