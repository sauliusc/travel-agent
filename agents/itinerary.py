"""Itinerary Planner agent: combines research + validated logistics + accommodation
into a day-by-day plan.
"""

from pathlib import Path

from agents.base import run_agent

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "itinerary.md").read_text()


def plan(combined_input_json: str) -> str:
    """Produce a day-by-day Itinerary from research, logistics, and accommodation input.

    Args:
        combined_input_json: JSON combining TripRequirements, research notes,
            logistics validation, and accommodation options
    """
    # No tools of its own — it reasons over the upstream agents' structured output.
    return run_agent(SYSTEM_PROMPT, [], combined_input_json)


def fix(itinerary_json: str, critic_issues: str) -> str:
    """Re-plan an itinerary to address specific issues raised by the Critic agent.

    Args:
        itinerary_json: the current Itinerary that needs fixing
        critic_issues: the Critic agent's issue list to address
    """
    task = f"Current itinerary:\n{itinerary_json}\n\nIssues to fix:\n{critic_issues}"
    return run_agent(SYSTEM_PROMPT, [], task)
