"""Structured Review/Critic output: each finding says what has to change
(the page only, or the itinerary) and whether it blocks publishing, so the
orchestrator reworks only what the finding actually needs."""

from typing import Literal

from pydantic import BaseModel, Field


class ReviewIssue(BaseModel):
    target: Literal["page", "itinerary"] = Field(
        description="'page' if fixing the HTML alone resolves it (wrong image path, missing tip, "
        "wording, missing button, page text not matching the data); 'itinerary' only if the "
        "plan data itself is wrong (wrong coordinates, overloaded day, driving limit, airport buffer)")
    severity: Literal["blocker", "minor"] = Field(
        description="'blocker' if a traveller would be misled or hurt (wrong place, unsafe road, "
        "broken link/image, missing safety tip, times off by more than 15 min); 'minor' otherwise")
    where: str = Field(description="day / section / stop")
    problem: str
    fix: str = Field(description="exactly what should change, with the correct value")


class Review(BaseModel):
    issues: list[ReviewIssue] = Field(default_factory=list)

    def blockers(self) -> list[ReviewIssue]:
        return [i for i in self.issues if i.severity == "blocker"]


def issues_text(issues: list[ReviewIssue]) -> str:
    return "\n".join(f"- [{i.target}/{i.severity}] {i.where}: {i.problem} -> {i.fix}" for i in issues)
