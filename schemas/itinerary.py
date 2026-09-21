"""Structured day-by-day itinerary, produced by the Itinerary Planner agent
and consumed by the Map and Page Designer agents.
"""

from pydantic import BaseModel, Field


class Stop(BaseModel):
    name: str
    lat: float
    lon: float
    arrive: str = Field(description="Arrival time as 'HH:MM'")
    depart: str = Field(description="Departure time as 'HH:MM'")
    google_maps_url: str
    notes: str | None = Field(default=None, description="e.g. a danger warning or off-road note")


class Day(BaseModel):
    number: int
    title: str
    stops: list[Stop]
    driving_minutes: int
    overnight_city: str


class Itinerary(BaseModel):
    days: list[Day]
