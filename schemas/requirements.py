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
    max_driving_hours_per_day: float = Field(default=4.0)
    priorities: list[str] = Field(
        default_factory=list, description="e.g. ['gamta', 'kultūra', 'poilsis']"
    )
    language: str = Field(default="lt", description="Output language for the generated page")
    notes: str | None = Field(default=None, description="Any free-text constraints not captured above")
