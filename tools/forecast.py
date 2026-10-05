"""Weather for each itinerary day at that day's overnight place (Open-Meteo).

Days within the 16-day forecast horizon get the real forecast; days further
out get the average of the same calendar date over the last 5 years, marked
source="climate" -- rerun the forecast stage closer to departure to replace
it with the real forecast.

`python3 tools/forecast.py --lat .. --lon .. --date 2026-10-30`
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from schemas.forecast import DayForecast, TripForecast
from schemas.itinerary import Itinerary

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HORIZON_DAYS = 15
CLIMATE_YEARS = 5

# WMO weather codes -> plain Lithuanian
_CODES = [
    ((0,), "Saulėta"), ((1, 2), "Mažai debesuota"), ((3,), "Debesuota"), ((45, 48), "Rūkas"),
    ((51, 53, 55, 56, 57), "Dulksna"), ((61, 63, 80, 81), "Lietus"), ((65, 82), "Smarkus lietus"),
    ((66, 67), "Lijundra"), ((71, 73, 75, 77, 85, 86), "Sniegas"), ((95, 96, 99), "Perkūnija"),
]


def describe_code(code: int) -> str:
    return next((text for codes, text in _CODES if code in codes), "Permainingi orai")


def _forecast(lat: float, lon: float, date: dt.date) -> dict:
    resp = httpx.get(FORECAST_URL, params={
        "latitude": lat, "longitude": lon, "timezone": "auto",
        "start_date": date.isoformat(), "end_date": date.isoformat(),
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
                 "precipitation_sum,wind_speed_10m_max",
    }, timeout=30)
    resp.raise_for_status()
    d = {k: v[0] for k, v in resp.json()["daily"].items()}
    return {
        "source": "forecast", "summary": describe_code(int(d["weather_code"])),
        "temp_min_c": d["temperature_2m_min"], "temp_max_c": d["temperature_2m_max"],
        "precip_chance_pct": int(d["precipitation_probability_max"] or 0),
        "precip_mm": d["precipitation_sum"] or 0.0, "wind_max_kmh": d["wind_speed_10m_max"],
    }


def _climate(lat: float, lon: float, date: dt.date) -> dict:
    rows = []
    for back in range(1, CLIMATE_YEARS + 1):
        try:
            day = date.replace(year=date.year - back)
        except ValueError:  # 29 Feb
            day = date.replace(year=date.year - back, day=28)
        resp = httpx.get(ARCHIVE_URL, params={
            "latitude": lat, "longitude": lon, "timezone": "auto",
            "start_date": day.isoformat(), "end_date": day.isoformat(),
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max",
        }, timeout=30)
        resp.raise_for_status()
        rows.append({k: v[0] for k, v in resp.json()["daily"].items() if k != "time"})
    avg = lambda k: round(sum((r[k] or 0) for r in rows) / len(rows), 1)
    wet = sum(1 for r in rows if (r["precipitation_sum"] or 0) > 1.0)
    chance = round(100 * wet / len(rows))
    return {
        "source": "climate",
        "summary": "Dažnai lyja" if chance >= 60 else "Kartais lyja" if chance >= 30 else "Dažniausiai sausa",
        "temp_min_c": avg("temperature_2m_min"), "temp_max_c": avg("temperature_2m_max"),
        "precip_chance_pct": chance, "precip_mm": avg("precipitation_sum"),
        "wind_max_kmh": avg("wind_speed_10m_max"),
    }


def day_weather(lat: float, lon: float, date: dt.date, today: dt.date) -> dict:
    return _forecast(lat, lon, date) if (date - today).days <= HORIZON_DAYS else _climate(lat, lon, date)


def trip_forecast(itinerary: Itinerary, start_date: dt.date, today: dt.date | None = None) -> TripForecast:
    today = today or dt.date.today()
    days = []
    for day in itinerary.days:
        if not day.stops:
            continue
        stop = day.stops[-1]  # where the day ends: the overnight place (or the airport)
        date = start_date + dt.timedelta(days=day.number - 1)
        days.append(DayForecast(
            day=day.number, date=date.isoformat(), place=day.overnight_city or stop.name,
            **day_weather(stop.lat, stop.lon, date, today),
        ))
    return TripForecast(generated_on=today.isoformat(), days=days)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    print(day_weather(args.lat, args.lon, dt.date.fromisoformat(args.date), dt.date.today()))


if __name__ == "__main__":
    main()
