"""Structured day-by-day itinerary, produced by the Itinerary Planner agent
and consumed by the Map and Page Designer agents.
"""

from typing import Literal

from pydantic import BaseModel, Field

# How the travellers get to a stop from the previous one.
TravelMode = Literal["car", "walk", "transit"]


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
    arrive_by: TravelMode = Field(
        default="car",
        description="how the travellers get here from the previous stop: 'car', 'walk' (up to ~5 km) or "
        "'transit' (public transport); ignored for a day's first stop. Never 'car' on a trip without a car.")
    transit: str = Field(
        default="",
        description="for arrive_by='transit': the best option, in the trip's language -- kind and line, "
        "where to board and get off, e.g. 'Metro M2: Rondo ONZ → Dworzec Wileński'")


class Day(BaseModel):
    number: int
    title: str
    stops: list[Stop]
    driving_minutes: int = Field(description="total car driving that day; 0 on a trip without a car")
    overnight_city: str


class Itinerary(BaseModel):
    days: list[Day]
