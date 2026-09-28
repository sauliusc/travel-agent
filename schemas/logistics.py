"""Structured Logistics Validator output. `passed` gates the pipeline: an
itinerary with unresolved blockers goes back to the planner, never to the page."""

from typing import Literal

from pydantic import BaseModel, Field


class LegCheck(BaseModel):
    day: int
    from_stop: str
    to_stop: str
    distance_km: float
    driving_minutes: int = Field(description="realistic time, mountain correction already applied")
    road: str = Field(description="plain-language road description for travellers, e.g. "
                      "'asphalted SH4 main road via Fier' -- no tool names or tag syntax")
    confirmed: bool = Field(description="true only if the road was confirmed paved and passable "
                            "(route_check LEG OK, or deeper research with a named, recent source)")
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
        description="short, friendly, practical driving tips for the trip page in the trip's "
        "language (e.g. 'Nesukite į Google Maps siūlomą kelią per Përmet -- jis žvyrkelis'). "
        "Only facts you confirmed; never uncertainty or internal process.")
    passed: bool = Field(description="true only if there are no blockers and every leg is confirmed")

    def blockers(self) -> list[LogisticsIssue]:
        unconfirmed = [
            LogisticsIssue(severity="blocker", where=f"Day {leg.day}: {leg.from_stop} -> {leg.to_stop}",
                           problem="road not confirmed paved/passable", fix="choose a confirmed route or change the stop")
            for leg in self.legs if not leg.confirmed
        ]
        return [i for i in self.issues if i.severity == "blocker"] + unconfirmed

    def ok(self) -> bool:
        # Don't trust the agent's own `passed` flag alone.
        return self.passed and not self.blockers()
