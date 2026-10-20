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
    maps_query: str = Field(
        default="",
        description="What to type into Google Maps to find exactly this place: its name plus town and "
        "country (e.g. 'Kalaja e Beratit, Berat, Albania'). If the name is ambiguous or not a listed "
        "place, its street address instead. Empty for a spot with neither (a viewpoint on a road) -- "
        "the coordinates are used then.")
    google_maps_url: str = Field(default="", description="filled in by code from maps_query / coordinates")
    notes: str | None = Field(default=None, description="e.g. a danger warning or off-road note")


class Day(BaseModel):
    number: int
    title: str
    stops: list[Stop]
    driving_minutes: int
    overnight_city: str


class Itinerary(BaseModel):
    days: list[Day]
