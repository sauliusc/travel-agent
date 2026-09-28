"""One-call leg check for the Logistics Validator: real driving distance/time
AND road type sampled along the actual route.

On a real run the agent guessed "midpoints" by straight-line interpolation
(often landing off any road), fired ~13 single-point Overpass calls in
parallel (rate-limited, each hitting the 120s Bash limit), then scraped OSRM
geometry itself with curl -- and the stage timed out at 1200s. This does the
whole leg deterministically: one OSRM request with geometry, N points spaced
evenly along it (endpoints excluded -- towns are always drivable), and ONE
batched Overpass request for all of them.

`python3 tools/route_check.py --from-lat .. --from-lon .. --to-lat .. --to-lon .. [--samples N]`
"""

import argparse
import math
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))  # so the CLI form can import tools/

from tools.osrm import MOUNTAIN_SPEED_FACTOR, OSRM_URL
from tools.overpass import road_types


def _seg_m(a: list[float], b: list[float]) -> float:
    kx = 111_320 * math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((b[0] - a[0]) * kx, (b[1] - a[1]) * 110_540)


def sample_along(coords: list[list[float]], n: int) -> list[tuple[float, float, float]]:
    """n points evenly spaced along a GeoJSON [lon, lat] polyline, endpoints
    excluded; returns (lat, lon, km_from_start)."""
    cum = [0.0]
    for a, b in zip(coords, coords[1:]):
        cum.append(cum[-1] + _seg_m(a, b))
    total = cum[-1]
    out, j = [], 0
    for i in range(1, n + 1):
        target = total * i / (n + 1)
        while j < len(cum) - 2 and cum[j + 1] < target:
            j += 1
        seg = cum[j + 1] - cum[j]
        t = 0.0 if seg == 0 else (target - cum[j]) / seg
        lon = coords[j][0] + t * (coords[j + 1][0] - coords[j][0])
        lat = coords[j][1] + t * (coords[j + 1][1] - coords[j][1])
        out.append((round(lat, 5), round(lon, 5), target / 1000))
    return out


def check_leg(from_lat: float, from_lon: float, to_lat: float, to_lon: float, samples: int | None = None) -> str:
    url = OSRM_URL.format(from_lon=from_lon, from_lat=from_lat, to_lon=to_lon, to_lat=to_lat)
    resp = httpx.get(url, params={"overview": "full", "geometries": "geojson"}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        return f"LEG ERROR: no route found (OSRM: {data.get('code', 'unknown error')})"

    route = data["routes"][0]
    km, minutes = route["distance"] / 1000, route["duration"] / 60
    lines = [
        f"Distance/time: {km:.0f} km, {minutes:.0f} min (OSRM flat-road estimate; "
        f"in mountain terrain multiply by {MOUNTAIN_SPEED_FACTOR})"
    ]
    if km < 2:
        lines.append("LEG OK: short in-town hop, no road-type sampling needed")
        return "\n".join(lines)

    n = samples or max(3, min(15, round(km / 10)))
    points = sample_along(route["geometry"]["coordinates"], n)
    verdicts = road_types([(lat, lon) for lat, lon, _ in points])
    bad = 0
    for (lat, lon, at_km), verdict in zip(points, verdicts):
        lines.append(f"  km {at_km:5.1f} ({lat}, {lon}): {verdict}")
        bad += not verdict.startswith("OK")
    lines.append(
        f"LEG OK: all {n} sampled points on paved drivable road" if bad == 0
        else f"LEG WARNING: {bad}/{n} sampled points are not confirmed paved/drivable -- see lines above"
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-lat", type=float, required=True)
    parser.add_argument("--from-lon", type=float, required=True)
    parser.add_argument("--to-lat", type=float, required=True)
    parser.add_argument("--to-lon", type=float, required=True)
    parser.add_argument("--samples", type=int, help="points to check along the route (default: ~1 per 10 km, 3-15)")
    args = parser.parse_args()
    print(check_leg(args.from_lat, args.from_lon, args.to_lat, args.to_lon, args.samples))


if __name__ == "__main__":
    main()
