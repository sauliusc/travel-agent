"""Itinerary Planner agent: combines research + validated logistics + accommodation
into a day-by-day plan.

Output is schema-validated (`claude -p --json-schema`, like requirements.py)
rather than free text: a real run once returned "the road-type sweep is running
in the background, I'll report the finished itinerary once it completes" as its
final answer, and that sentence was stored and passed downstream as if it were
the itinerary. A `claude -p` call is a single synchronous turn -- there is no
"later" -- so the schema forces a complete Itinerary or a clear failure.
"""

import json
from pathlib import Path

from pydantic import BaseModel, Field

from agents.base import ClaudeCLIError, _invoke_claude, run_structured
from schemas.itinerary import Itinerary

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "itinerary.md").read_text()

# Validation via OSRM/Overpass (with mirror fallback + retries) can take longer
# than the 600s default; a real run timed out at exactly 600s inside fix().
TIMEOUT = 1200

COMPLETION_RULE = (
    "Finish all checks within this turn and return the complete final itinerary. "
    "Do not start background jobs or promise to report results later -- there is "
    "no later turn."
)


def _run(task: str) -> str:
    payload = _invoke_claude(
        SYSTEM_PROMPT,
        allowed_tools=[],
        user_input=f"{task}\n\n{COMPLETION_RULE}",
        timeout=TIMEOUT,
        extra_args=["--json-schema", json.dumps(Itinerary.model_json_schema())],
        # --allowedTools [] only skips permission prompts; under
        # --permission-mode auto the planner still ran Bash (OSRM/Overpass
        # sweeps) on real runs, doing the Logistics Validator's job and eating
        # minutes. Deny outright -- it plans, logistics validates.
        disallowed_tools=["Bash", "WebSearch", "WebFetch"],
    )
    structured = payload.get("structured_output")
    if structured is not None:
        return Itinerary.model_validate(structured).model_dump_json()

    text = payload.get("result")
    if text is None:
        raise ClaudeCLIError(
            f"claude JSON output missing both 'structured_output' and 'result': {payload!r}"
        )
    try:
        return Itinerary.model_validate_json(text).model_dump_json()
    except Exception as e:
        raise ClaudeCLIError(
            f"Itinerary Planner did not return a valid Itinerary: {text[:500]!r}"
        ) from e


def plan(combined_input_json: str) -> str:
    """Produce a day-by-day Itinerary (as JSON) from research, logistics, and accommodation input."""
    return _run(combined_input_json)


class ItineraryFix(BaseModel):
    itinerary: Itinerary
    changed_days: list[int] = Field(
        description="numbers of every day whose content differs from the current itinerary, "
        "including knock-on changes (e.g. the next day now starts from a different hotel)")
    change_summary: str = Field(description="one or two sentences: what changed and on which days")


FIX_RULES = (
    "Change only what the issues/request require. Copy every other day exactly as it is in "
    "the current itinerary -- same stops, times, notes, wording. List in `changed_days` every "
    "day you changed, including knock-on changes; days not listed are restored from the "
    "current itinerary automatically."
)


def fix(itinerary_json: str, issues: str) -> tuple[str, str]:
    """Rework an itinerary to address issues (a traveller's change request,
    logistics blockers or critic findings) with minimal change.

    Returns (itinerary JSON, change summary). Days the agent didn't declare
    as changed are restored from the current itinerary in code, so untouched
    days are guaranteed identical -- not just asked to stay so.
    """
    current = Itinerary.model_validate_json(itinerary_json)
    result = run_structured(
        SYSTEM_PROMPT, [],
        f"Current itinerary:\n{itinerary_json}\n\nIssues to fix:\n{issues}\n\n{FIX_RULES}\n\n{COMPLETION_RULE}",
        ItineraryFix, timeout=TIMEOUT, disallowed_tools=["Bash", "WebSearch", "WebFetch"],
    )
    before = {d.number: d for d in current.days}
    changed = set(result.changed_days)
    days = [before[d.number] if d.number in before and d.number not in changed else d
            for d in result.itinerary.days]
    return Itinerary(days=days).model_dump_json(), result.change_summary
