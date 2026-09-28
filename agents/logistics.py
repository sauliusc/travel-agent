"""Logistics Validator agent: checks every itinerary leg against real road data."""

from pathlib import Path

from agents.base import run_agent

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "logistics.md").read_text()

# Per-leg OSRM + multi-point Overpass checks (with mirror fallback/backoff) can
# exceed the 600s default on a multi-day trip.
TIMEOUT = 1200

TOOL_HINT = (
    "Check each leg with ONE call: `python3 tools/route_check.py --from-lat .. --from-lon .. "
    "--to-lat .. --to-lon ..` -- it returns real distance/time and the road type at points "
    "sampled along the actual route, ending in a `LEG OK` or `LEG WARNING` line. Run legs one "
    "after another, not in parallel (Overpass rate-limits parallel requests). Do not call "
    "OSRM/Overpass with curl yourself. `python3 tools/overpass.py --lat .. --lon ..` is only for "
    "spot-checking one specific point."
)


def validate(itinerary_json: str) -> str:
    """Validate an itinerary's driving legs and flag off-road/overloaded days.

    Args:
        itinerary_json: JSON-serialized Itinerary (see schemas/itinerary.py)
    """
    task = f"{itinerary_json}\n\n{TOOL_HINT}"
    return run_agent(SYSTEM_PROMPT, ["Bash"], task, timeout=TIMEOUT)
