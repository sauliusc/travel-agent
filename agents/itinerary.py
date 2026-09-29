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

from agents.base import ClaudeCLIError, _invoke_claude
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


def fix(itinerary_json: str, critic_issues: str) -> str:
    """Re-plan an itinerary (as JSON) to address specific issues raised by the Critic agent."""
    return _run(f"Current itinerary:\n{itinerary_json}\n\nIssues to fix:\n{critic_issues}")
