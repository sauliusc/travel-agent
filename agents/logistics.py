"""Logistics Validator agent: checks every itinerary leg against real road data,
researching deeper when the tools can't confirm a road."""

import json
from pathlib import Path

from agents.base import ClaudeCLIError, _invoke_claude
from schemas.logistics import LogisticsReport

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "logistics.md").read_text()

# route_check per leg plus web research on any leg it can't confirm.
TIMEOUT = 1200

TOOL_HINT = (
    "Check each leg with ONE call: `python3 tools/route_check.py --from-lat .. --from-lon .. "
    "--to-lat .. --to-lon ..` -- it returns real distance/time and the road type at points "
    "sampled along the actual route, ending in `LEG OK`, `LEG WARNING` (not paved/drivable) or "
    "`LEG UNKNOWN` (road data service unreachable -- not a road problem; retry that leg once, then "
    "research it as unconfirmed). Run legs one "
    "after another, not in parallel (Overpass rate-limits parallel requests). Do not call "
    "OSRM/Overpass with curl yourself. `python3 tools/overpass.py --lat .. --lon ..` is only for "
    "spot-checking one specific point."
)


REUSE_HINT = (
    "Previous validation report for an earlier version of this itinerary is below. For a leg "
    "with the same from/to stops as a leg confirmed there, reuse that result (distance, time, "
    "road, evidence) without running route_check again; check only new or changed legs. "
    "Daily totals and the airport buffer must still be recomputed for the current plan."
)


def validate(itinerary_json: str, previous: LogisticsReport | None = None) -> LogisticsReport:
    """Validate an itinerary's driving legs; returns a structured report whose
    ok() decides whether the itinerary may proceed to the page. With
    `previous`, already-confirmed unchanged legs are reused, not re-checked."""
    task = f"{itinerary_json}\n\n{TOOL_HINT}"
    if previous is not None:
        task += f"\n\n{REUSE_HINT}\n{previous.model_dump_json()}"
    payload = _invoke_claude(
        SYSTEM_PROMPT,
        allowed_tools=["Bash", "WebSearch", "WebFetch"],
        user_input=task,
        timeout=TIMEOUT,
        extra_args=["--json-schema", json.dumps(LogisticsReport.model_json_schema())],
    )
    structured = payload.get("structured_output")
    if structured is not None:
        return LogisticsReport.model_validate(structured)
    text = payload.get("result")
    if text is None:
        raise ClaudeCLIError(f"claude JSON output missing both 'structured_output' and 'result': {payload!r}")
    try:
        return LogisticsReport.model_validate_json(text)
    except Exception as e:
        raise ClaudeCLIError(f"Logistics Validator did not return a valid report: {text[:500]!r}") from e
