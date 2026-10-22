"""Weather & Season agent: checks seasonal fit for the destination and dates."""

from pathlib import Path

from agents.base import run_agent

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "weather.md").read_text()

TOOL_HINT = (
    "Use Bash to check typical conditions: `python3 tools/open_meteo.py --lat .. "
    "--lon .. --month <1-12>`. Use WebSearch for anything not covered by that "
    "(e.g. seasonal road closures)."
)


def check(requirements_json: str) -> str:
    """Check seasonal fit (temperature, rain, road-access issues) for the trip dates.

    Args:
        requirements_json: JSON-serialized TripRequirements
    """
    task = f"{requirements_json}\n\n{TOOL_HINT}"
    return run_agent(SYSTEM_PROMPT, ["Bash", "WebSearch"], task)
