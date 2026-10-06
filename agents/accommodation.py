"""Accommodation agent: finds lodging options per overnight city via web search."""

from pathlib import Path

from pydantic import BaseModel, Field

from agents.base import run_agent, run_structured

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "accommodation.md").read_text()


def find(context_json: str) -> str:
    """Find 2-3 accommodation options per overnight city.

    Args:
        context_json: JSON combining TripRequirements and the Research agent's
            candidate overnight cities (or the itinerary's overnight_city fields,
            once the itinerary exists)
    """
    return run_agent(SYSTEM_PROMPT, ["WebSearch"], context_json)


class AccommodationUpdate(BaseModel):
    changed: bool = Field(description="false if the change request doesn't concern accommodation")
    accommodation: str = Field(description="the full updated accommodation plan (unchanged text if changed=false)")


UPDATE_RULES = """You are updating an existing accommodation plan with a change request from the
traveller. If the request concerns where they stay (adding, replacing or removing a hotel,
a night, a city), apply it: for hotels they name, look up the real address, typical price
for the dates, parking and contacts, and keep everything else in the plan as it is. If the
request doesn't concern accommodation at all, return changed=false and the plan unchanged."""


def update(current: str, modification: str, requirements_json: str) -> AccommodationUpdate:
    """Apply a traveller's free-text change to the existing accommodation plan."""
    return run_structured(
        f"{SYSTEM_PROMPT}\n\n{UPDATE_RULES}", ["WebSearch", "WebFetch"],
        f"Trip requirements:\n{requirements_json}\n\nCurrent accommodation plan:\n{current}\n\n"
        f"Change request:\n{modification}",
        AccommodationUpdate, timeout=900,
    )
