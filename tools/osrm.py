"""Driving time/distance between two points via a real road route (OSRM).

Callable both as a Python function and as a CLI script, so the Logistics
Validator agent (running under Claude Code) can invoke it via the Bash
tool: `python3 tools/osrm.py --from-lat .. --from-lon .. --to-lat .. --to-lon ..`
"""

import argparse

import httpx

OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{from_lon},{from_lat};{to_lon},{to_lat}"

# Mountain roads run well below OSRM's flat-road estimate; apply a correction
# so the Logistics Validator doesn't repeat the SH74 mistake (an estimated
# 1.5h that was actually a dangerous 4x4-only track).
MOUNTAIN_SPEED_FACTOR = 1.3


def driving_time(from_lat: float, from_lon: float, to_lat: float, to_lon: float) -> str:
    """Return driving distance (km) and time (min) between two points via the real road network."""
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-lat", type=float, required=True)
    parser.add_argument("--from-lon", type=float, required=True)
    parser.add_argument("--to-lat", type=float, required=True)
    parser.add_argument("--to-lon", type=float, required=True)
    args = parser.parse_args()
    print(driving_time(args.from_lat, args.from_lon, args.to_lat, args.to_lon))


if __name__ == "__main__":
    main()
