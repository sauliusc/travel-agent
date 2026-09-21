"""Road-type lookup near a point via the Overpass API (OpenStreetMap).

Used by the Logistics Validator agent to catch routes that pass through
unpaved 4x4-only tracks (highway=track) before they end up in an itinerary —
the exact mistake behind the SH74 (Osum -> Permet) route in the Albania trip.
"""

import httpx
from anthropic import beta_tool

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# highway values that mean "not a standard rental car road"
OFFROAD_TAGS = {"track", "path", "bridleway", "footway"}


@beta_tool
def road_type(lat: float, lon: float, radius_m: int = 200) -> str:
    """Return the OSM highway type(s) found near a coordinate, flagging off-road tracks.

    Args:
        lat: latitude of the point to check
        lon: longitude of the point to check
        radius_m: search radius in meters around the point (default 200)
    """
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
