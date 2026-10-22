"""Per-day weather for the trip, built by code (tools/forecast.py), no LLM."""

from typing import Literal

from pydantic import BaseModel


class DayForecast(BaseModel):
    day: int
    date: str
    place: str
    source: Literal["forecast", "climate"]  # real forecast (<=16 days ahead) or multi-year average
    summary: str  # plain words in Lithuanian, e.g. "Saulėta", "Lietus"
    temp_min_c: float
    temp_max_c: float
    precip_chance_pct: int
    precip_mm: float
    wind_max_kmh: float


class TripForecast(BaseModel):
    generated_on: str
    days: list[DayForecast]
