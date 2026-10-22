"""Historical climate lookup for a location/month via the Open-Meteo archive API.

Callable both as a Python function and as a CLI script, so the Weather
agent (running under Claude Code) can invoke it via the Bash tool:
`python3 tools/open_meteo.py --lat .. --lon .. --month 10`
"""

import argparse
import datetime

import httpx

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def climate_summary(lat: float, lon: float, month: int) -> str:
    """Return typical temperature and precipitation for a location in a given month.

    Uses the last full calendar year's data for that month as a proxy for typical
    conditions.
    """
    last_year = datetime.date.today().year - 1
    start = f"{last_year}-{month:02d}-01"
    # 28 days is safe for every month; avoids computing the exact last day.
    end_day = 28
    end = f"{last_year}-{month:02d}-{end_day:02d}"

    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "timezone": "auto",
    }
    resp = httpx.get(ARCHIVE_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json().get("daily", {})
    highs = data.get("temperature_2m_max", [])
    lows = data.get("temperature_2m_min", [])
    precip = data.get("precipitation_sum", [])
    if not highs:
        return "No climate data available for this location/month"

    avg_high = sum(highs) / len(highs)
    avg_low = sum(lows) / len(lows)
    rainy_days = sum(1 for p in precip if p and p > 1.0)

    return (
        f"Typical for month {month} (based on {last_year}): "
        f"{avg_low:.0f}-{avg_high:.0f}C, {rainy_days}/{len(highs)} days with >1mm rain"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--month", type=int, required=True, choices=range(1, 13))
    args = parser.parse_args()
    print(climate_summary(args.lat, args.lon, args.month))


if __name__ == "__main__":
    main()
