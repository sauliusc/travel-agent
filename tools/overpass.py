"""Road-type lookup near a point via the Overpass API (OpenStreetMap).

Used by the Logistics Validator agent to catch routes that pass through
unpaved 4x4-only tracks (highway=track) before they end up in an itinerary —
the exact mistake behind the SH74 (Osum -> Permet) route in the Albania trip.

Callable both as a Python function and as a CLI script, so the agent
(running under Claude Code) can invoke it via the Bash tool:
`python3 tools/overpass.py --lat .. --lon .. [--radius-m 200]`
"""

import argparse

import httpx

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# highway values that mean "not a standard rental car road"
OFFROAD_TAGS = {"track", "path", "bridleway", "footway"}


def road_type(lat: float, lon: float, radius_m: int = 200) -> str:
    """Return the OSM highway type(s) found near a coordinate, flagging off-road tracks."""
    query = f"""
    [out:json][timeout:25];
    way(around:{radius_m},{lat},{lon})["highway"];
    out tags;
    """
    resp = httpx.post(OVERPASS_URL, data={"data": query}, timeout=30)
    resp.raise_for_status()
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
