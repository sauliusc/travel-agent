"""Structured Logistics Validator output. `passed` gates the pipeline: an
itinerary with unresolved blockers goes back to the planner, never to the page."""

from typing import Literal

from pydantic import AliasChoices, BaseModel, Field

from schemas.itinerary import TravelMode

TransitKind = Literal["", "metro", "bus", "tram", "trolleybus", "train", "ferry", "funicular"]

# Shown next to each leg on the page; picked by code from mode/kind.
ICONS = {"car": "🚗", "walk": "🚶", "metro": "🚇", "bus": "🚌", "tram": "🚋", "trolleybus": "🚎",
         "train": "🚆", "ferry": "⛴️", "funicular": "🚠"}


class LegCheck(BaseModel):
    day: int
    from_stop: str
    to_stop: str
    mode: TravelMode = Field(default="car", description="the to-stop's `arrive_by` in the itinerary")
    distance_km: float
    minutes: int = Field(
        validation_alias=AliasChoices("minutes", "driving_minutes"),  # reports saved before modes existed
        description="realistic door-to-door time in this leg's mode: car (mountain correction applied), "
        "walk, or transit (walking to/from the stops, typical wait and ride)")
    transit_kind: TransitKind = Field(default="", description="for a transit leg: the main vehicle")
    transit: str = Field(default="", description="for a transit leg, in the trip's language: line, where "
                         "to board and get off, how often it runs, ticket, e.g. 'Metro M2 iš Rondo ONZ iki "
                         "Dworzec Wileński (4 stotelės, kas 5 min.), bilietas 4,40 zł'")
    road: str = Field(description="plain-language description for travellers: the road for a car leg "
                      "('asphalted SH4 main road via Fier'), the way for a walk ('per senamiestį'), "
                      "empty for transit -- no tool names or tag syntax")
    confirmed: bool = Field(description="car: road confirmed paved and passable (route_check LEG OK, or "
                            "deeper research with a named, recent source); walk: always true; transit: the "
                            "line was confirmed to run on the trip dates")
    evidence: str = Field(description="internal: what confirmed it (route_check result, sources)")


class LogisticsIssue(BaseModel):
    severity: Literal["blocker", "note"] = Field(
        description="blocker: unsafe/unconfirmed road, over the daily driving limit, or airport "
        "buffer under 2h -- the itinerary must change. note: minor, safe to ship")
    where: str = Field(description="day and leg, e.g. 'Day 3: Berat -> Tepelene'")
    problem: str
    fix: str = Field(description="concrete change: other road, drop/move a stop, split the day")


class LogisticsReport(BaseModel):
    legs: list[LegCheck]
    issues: list[LogisticsIssue]
    traveler_tips: list[str] = Field(
        default_factory=list,
        description="short, friendly, practical travel tips (driving, or public transport tickets) for the trip page in the trip's "
        "language (e.g. 'Nesukite į Google Maps siūlomą kelią per Përmet -- jis žvyrkelis'). "
        "Only facts you confirmed; never uncertainty or internal process.")
    passed: bool = Field(description="true only if there are no blockers and every leg is confirmed")

    def blockers(self) -> list[LogisticsIssue]:
        unconfirmed = [
            LogisticsIssue(severity="blocker", where=f"Day {leg.day}: {leg.from_stop} -> {leg.to_stop}",
                           problem="road not confirmed paved/passable", fix="choose a confirmed route or change the stop")
            if leg.mode == "car" else
            LogisticsIssue(severity="blocker", where=f"Day {leg.day}: {leg.from_stop} -> {leg.to_stop}",
                           problem="public transport option not confirmed (time must be the transit time, "
                                   "not a driving time)",
                           fix="check the line on the operator's site / journey planner, or name another option")
            for leg in self.legs if not leg.confirmed
        ]
        return [i for i in self.issues if i.severity == "blocker"] + unconfirmed

    def ok(self) -> bool:
        # Don't trust the agent's own `passed` flag alone.
        return self.passed and not self.blockers()
