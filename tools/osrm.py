"""Driving time/distance between two points via a real road route (OSRM)."""

import httpx
from anthropic import beta_tool

OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{from_lon},{from_lat};{to_lon},{to_lat}"

# Mountain roads run well below OSRM's flat-road estimate; apply a correction
# so the Logistics Validator doesn't repeat the SH74 mistake (an estimated
# 1.5h that was actually a dangerous 4x4-only track).
MOUNTAIN_SPEED_FACTOR = 1.3


@beta_tool
def driving_time(from_lat: float, from_lon: float, to_lat: float, to_lon: float) -> str:
    """Return driving distance (km) and time (min) between two points via the real road network.

    Args:
        from_lat: starting point latitude
        from_lon: starting point longitude
        to_lat: destination latitude
        to_lon: destination longitude
    """
    url = OSRM_URL.format(from_lon=from_lon, from_lat=from_lat, to_lon=to_lon, to_lat=to_lat)
    resp = httpx.get(url, params={"overview": "false"}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        return f"No route found between the two points (OSRM: {data.get('code', 'unknown error')})"

    route = data["routes"][0]
    distance_km = route["distance"] / 1000
    duration_min = route["duration"] / 60
    return (
        f"{distance_km:.0f} km, {duration_min:.0f} min (OSRM flat-road estimate; "
        f"in mountain terrain multiply by {MOUNTAIN_SPEED_FACTOR} for a realistic time)"
    )
