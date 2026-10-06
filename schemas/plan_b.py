"""Bad-weather alternative (Plan B) per itinerary day."""

from pydantic import BaseModel, Field

from schemas.itinerary import Stop


class PlanBDay(BaseModel):
    day: int
    needed: bool = Field(description="false if the day's main plan doesn't depend on the weather "
                         "(mostly indoor, city, or just driving)")
    weather_sensitive: str = Field(default="", description="which main-plan stops suffer in bad weather and why, "
                                   "in the trip's language")
    title: str = Field(default="", description="short title of the alternative, in the trip's language")
    stops: list[Stop] = Field(default_factory=list, description="full alternative day, in order: same first stop "
                              "as the main plan, same last stop (overnight place / airport) as the main plan")
    tip: str = Field(default="", description="one practical sentence, e.g. booking or opening hours")


class PlanB(BaseModel):
    days: list[PlanBDay]


class PlanBChecked(PlanB):
    """PlanB after the code checks, with per-day driving and route links."""
    driving_minutes: dict[int, int] = Field(default_factory=dict)
    route_urls: dict[int, list[str]] = Field(default_factory=dict)
