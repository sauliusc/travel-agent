"""Structured trip requirements, produced by the Requirements Analyst agent."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class TripRequirements(BaseModel):
    destination: str = Field(description="Destination country or region, e.g. 'Albanija'")
    trip_type: Literal["roundtrip", "linear"] = Field(
        description="'roundtrip' if the car returns to the start, 'linear' otherwise"
    )
    start_date: date
    end_date: date
    travelers: int = Field(ge=1)
    budget_eur: int | None = Field(default=None, description="Total budget in EUR, if given")
    airport: str = Field(description="IATA code of the return airport, e.g. 'TIA'")
    return_flight_time: str | None = Field(
        default=None, description="Return flight departure time as 'HH:MM', if known"
    )
    transport: Literal["car", "public_transport"] = Field(
        default="car",
        description="How the travellers get between places: 'car' if they rent or bring a car (road "
        "trip), 'public_transport' if the request has no car (city trip, flying in and getting around "
        "by metro/bus/train). Walking short distances is part of both.")
    max_driving_hours_per_day: float = Field(default=4.0)
    priorities: list[str] = Field(
        default_factory=list, description="e.g. ['gamta', 'kultūra', 'poilsis']"
    )
    accommodation_type: str | None = Field(
        default=None, description="Preferred kind of stay, e.g. 'apartamentai', 'viešbutis', 'hostelis', if given")
    max_price_per_night_eur: int | None = Field(
        default=None, description="Upper limit per night for the whole group in EUR, if given")
    accommodation_area: str | None = Field(
        default=None, description="Preferred location, e.g. 'centras', 'prie viešojo transporto', 'rami vieta', if given")
    language: str = Field(default="lt", description="Output language for the generated page")
    notes: str | None = Field(default=None, description="Any free-text constraints not captured above")
